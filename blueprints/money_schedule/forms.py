from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField
from wtforms.validators import DataRequired


class AssetIncludeForm(FlaskForm):
    account_id = IntegerField(validators=[DataRequired()])
    include = BooleanField()
