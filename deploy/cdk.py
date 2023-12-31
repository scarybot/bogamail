#!/usr/bin/env python3
import os

import aws_cdk as cdk

from bogamail_stack import BogamailStack


app = cdk.App()
BogamailStack(app, "BogamailStack")

app.synth()
