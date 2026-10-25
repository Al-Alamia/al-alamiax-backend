from django.db import models

class UserTypes (models.TextChoices):
    AGENT = ("AGENT", "Agent")
    MANAGER = ("MANAGER", "Manager")
    OWNER = ('OWNER','Owner')
    HR = ('HR','HR')


class RequestStatuses (models.TextChoices):
    PENDING = ("PENDING", "Pending")
    ACCEPTED = ("ACCEPTED", "Accepted")
    REJECTED = ('REJECTED','Rejected')


class DepartmentCodes (models.TextChoices):
    MARKETING = ("marketing", "Marketing")
    SALES = ("sales", "Sales")
    TECHNICAL = ("technical", "Technical")
    OTHER = ("other", "Other")


class StockMarkets (models.TextChoices):
    SAUDI = ("saudi", "Saudi")
    AMERICAN = ("american", "American")
    EMIRATI = ("emirati", "Emirati")
    OTHER = ("other", "Other")


class LeadStatuses (models.TextChoices):
    NEW = ("new", "New")
    ASSIGNED = ("assigned", "Assigned")
    CONTACTED = ("contacted", "Contacted")
    NO_ANSWER = ("no_answer", "No Answer")
    INTERESTED = ("interested", "Interested")
    NOT_INTERESTED = ("not_interested", "Not Interested")
    SUBSCRIBER = ("subscriber", "Subscriber")


class CallStatuses (models.TextChoices):
    PENDING = ("pending", "Pending")
    CALLED = ("called", "Called")
    NO_ANSWER = ("no_answer", "No Answer")
    INTERESTED = ("interested", "Interested")
    NOT_INTERESTED = ("not_interested", "Not Interested")
    CALLBACK_REQUESTED = ("callback_requested", "Callback Requested")


class AssignmentKinds (models.TextChoices):
    SALES = ("sales", "Sales")
    CS = ("cs", "Customer Service")


class LeadUpdateTypes (models.TextChoices):
    CREATED = ("created", "Created")
    EDITED = ("edited", "Edited")
    STATUS = ("status", "Status")
    CALL_STATUS = ("call_status", "Call Status")
    ASSIGNED = ("assigned", "Assigned")
    RETURNED = ("returned", "Returned")
    HIDDEN = ("hidden", "Hidden")
    UNHIDDEN = ("unhidden", "Unhidden")
    NOTE = ("note", "Note")
