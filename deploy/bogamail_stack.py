from aws_cdk import Duration, Stack, aws_dynamodb as dynamodb
from constructs import Construct
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sqs as sqs
from aws_cdk.aws_sns_subscriptions import SqsSubscription
from aws_cdk import aws_lambda as lambda_
from aws_cdk.aws_lambda_event_sources import SqsEventSource
from aws_cdk.aws_lambda_python_alpha import PythonFunction
from aws_cdk import aws_iam as iam
from aws_cdk.aws_iam import ServicePrincipal
from aws_cdk import aws_ses as ses
from aws_cdk import aws_ses_actions as ses_actions
from aws_cdk import aws_ssm as ssm
from aws_cdk.aws_secretsmanager import Secret


class BogamailStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        receive_topic = sns.Topic(self, "BogamailReceiveTopic")

        receive_queue = sqs.Queue(
            self, "BogamailReceiveQueue", visibility_timeout=Duration.seconds(300)
        )

        client_queue = sqs.Queue(
            self, "BogamailClientQueue", visibility_timeout=Duration.seconds(300)
        )

        send_queue = sqs.Queue(
            self, "BogamailSendQueue", visibility_timeout=Duration.seconds(300)
        )

        receive_topic.add_subscription(SqsSubscription(receive_queue))

        mail_table = dynamodb.Table(
            self,
            "MailTable",
            partition_key=dynamodb.Attribute(
                name="sender", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        mail_table.add_global_secondary_index(
            partition_key=dynamodb.Attribute(
                name="thread_previous_id", type=dynamodb.AttributeType.STRING
            ),
            index_name="ThreadIndex",
            projection_type=dynamodb.ProjectionType.ALL,
        )

        mail_table.add_global_secondary_index(
            partition_key=dynamodb.Attribute(
                name="sent", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="send_after", type=dynamodb.AttributeType.NUMBER
            ),
            index_name="SendIndex",
            projection_type=dynamodb.ProjectionType.ALL,
        )

        receive_topic.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["sns:Publish"],
                principals=[ServicePrincipal("ses.amazonaws.com")],
                resources=[receive_topic.topic_arn],
            )
        )

        receive_function = PythonFunction(
            self,
            "BogamailReceiveFunction",
            entry="../receive_lambda",
            index="lambda_handler.py",
            handler="lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_8,
            environment={
                "MAIL_TABLE": mail_table.table_name,
                "RECEIVE_QUEUE_URL": receive_queue.queue_url,
                "CLIENT_QUEUE_URL": client_queue.queue_url,
            },
        )

        send_function = PythonFunction(
            self,
            "BogamailSendFunction",
            entry="../send_lambda",
            index="lambda_handler.py",
            handler="lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_8,
            environment={
                "MAIL_TABLE": mail_table.table_name,
                "SEND_QUEUE_URL": client_queue.queue_url,
            },
        )

        rule_set = ses.ReceiptRuleSet(self, "BogamailRuleSet")

        receipt_rule = ses.ReceiptRule(
            self,
            "BogamailReceivingRule",
            rule_set=rule_set,
            recipients=["mailer-daemon@mylocal.zone"],
        )

        mail_table_parameter = ssm.StringParameter(
            self,
            "MailTableSsmParameter",
            parameter_name="/bogamail/mail_table",
            string_value=mail_table.table_name,
        )

        client_queue_parameter = ssm.StringParameter(
            self,
            "ClientQueueSsmParameter",
            parameter_name="/bogamail/client_queue_url",
            string_value=client_queue.queue_url,
        )

        mail_table_parameter.grant_read(receive_function)
        mail_table.grant_write_data(receive_function)
        client_queue.grant_send_messages(receive_function)
        receipt_rule.add_action(ses_actions.Sns(topic=receive_topic))
        receive_function.add_event_source(SqsEventSource(receive_queue))
        send_function.add_event_source(SqsEventSource(send_queue))
        send_function.grant_read(mail_table)
        send_function.grant_read_params(client_queue_parameter)
