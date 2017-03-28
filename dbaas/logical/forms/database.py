# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals
import logging
from django.utils.translation import ugettext_lazy as _
from django.forms import models
from django import forms
from account.models import Team
from dbaas_cloudstack.models import CloudStackPack
from drivers.factory import DriverFactory
from backup.models import Snapshot
from physical.models import Plan, Environment, Engine
from logical.forms.fields import AdvancedModelChoiceField
from logical.models import Database, Project
from logical.validators import database_name_evironment_constraint

LOG = logging.getLogger(__name__)


class DatabaseForm(models.ModelForm):
    plan = AdvancedModelChoiceField(queryset=Plan.objects.filter(is_active='True'),
                                    required=False, widget=forms.RadioSelect,
                                    empty_label=None)
    engine = forms.ModelChoiceField(queryset=Engine.objects)
    environment = forms.ModelChoiceField(queryset=Environment.objects)

    class Meta:
        model = Database
        fields = (
            'name', 'description', 'subscribe_to_email_events',
            'project', 'team', 'is_in_quarantine',
        )

    def remove_fields_not_in_models(self):
        fields_to_remove = ["plan", "engine", "environment"]
        for field_name in fields_to_remove:
            if field_name in self.fields:
                del self.fields[field_name]

    def __init__(self, *args, **kwargs):

        super(DatabaseForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            LOG.debug("instance database form found! %s" % instance)
            # remove fields not in models
            self.remove_fields_not_in_models()

        else:
            self.fields['is_in_quarantine'].widget = forms.HiddenInput()

    def _validate_description(self, cleaned_data):
        if 'description' in cleaned_data:
            if not cleaned_data.get('description', None):
                self._errors["description"] = self.error_class(
                    [_("Description: This field is required.")])

    def _validate_project(self, cleaned_data):
        if 'project' in cleaned_data:
            if not cleaned_data.get('project', None):
                self._errors["project"] = self.error_class(
                    [_("Project: This field is required.")])

    def _validate_team(self, cleaned_data):
        if 'team' in cleaned_data:
            if not cleaned_data['team']:
                LOG.warning("No team specified in database form")
                self._errors["team"] = self.error_class(
                    [_("Team: This field is required.")])

    def _validate_team_resources(self, cleaned_data):
        team = cleaned_data['team']

        if team:
            dbs = team.databases_in_use_for(cleaned_data['environment'])
            database_alocation_limit = team.database_alocation_limit
            LOG.debug("dbs: %s | type: %s" % (dbs, type(dbs)))

            if (database_alocation_limit != 0 and len(dbs) >= database_alocation_limit):
                LOG.warning("The database alocation limit of %s has been exceeded for the selected team %s => %s" % (
                    database_alocation_limit, team, list(dbs)))
                self._errors["team"] = self.error_class(
                    [_("The database alocation limit of %s has been exceeded for the selected team: %s") % (database_alocation_limit, list(dbs))])

    def _validate_name(self, cleaned_data):
        if len(cleaned_data['name']) > 40:
            self._errors["name"] = self.error_class(
                [_("Database name too long")])

        plan = cleaned_data['plan']
        driver = DriverFactory.get_driver_class(plan.engines[0].name)
        if cleaned_data['name'] in driver.RESERVED_DATABASES_NAME:
            raise forms.ValidationError(
                _("%s is a reserved database name" % cleaned_data['name']))

    def clean(self):
        cleaned_data = super(DatabaseForm, self).clean()

        # if there is an instance, that means that we are in a edit page and therefore
        # it should return the default cleaned_data
        if self.instance and self.instance.id:
            self._validate_project(cleaned_data)
            self._validate_description(cleaned_data)
            self._validate_team(cleaned_data)
            return cleaned_data

        if not self.is_valid():
            raise forms.ValidationError(self.errors)

        if 'plan' in cleaned_data:
            plan = cleaned_data.get('plan', None)
            if not plan:
                self._errors["plan"] = self.error_class(
                    [_("Plan: This field is required.")])

        self._validate_name(cleaned_data)
        self._validate_project(cleaned_data)
        self._validate_description(cleaned_data)
        self._validate_team(cleaned_data)

        if 'environment' in cleaned_data:
            environment = cleaned_data.get('environment', None)
            database_name = cleaned_data.get('name', None)
            if not environment or environment not in plan.environments.all():
                raise forms.ValidationError(
                    _("Invalid plan for selected environment."))

            if Database.objects.filter(name=database_name,
                                       environment=environment):
                self._errors["name"] = self.error_class(
                    [_("this name already exists in the selected environment")])
                del cleaned_data["name"]

        self._validate_team_resources(cleaned_data)
        if database_name_evironment_constraint(database_name, environment.name):
            raise forms.ValidationError(
                _('%s already exists in production!') % database_name
            )

        if self._errors:
            return cleaned_data

        return cleaned_data

    def save_m2m(self, *args, **kwargs):
        pass


class LogDatabaseForm(forms.Form):
    database_id = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):

        super(LogDatabaseForm, self).__init__(*args, **kwargs)
        if 'initial' in kwargs:
            instance = Database.objects.get(
                id=kwargs['initial']['database_id'])

            if instance:
                LOG.debug("instance database form found! %s" % instance)


class DatabaseDetailsForm(forms.ModelForm):

    class Meta:
        model = Database
        fields = [
            'team', 'project', 'is_protected', 'subscribe_to_email_events',
            'description'
        ]

    def __init__(self, *args, **kwargs):
        super(DatabaseDetailsForm, self).__init__(*args, **kwargs)

        self.fields['team'].required = True
        self.fields['project'].required = True
        self.fields['description'].required = True
