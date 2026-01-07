from rest_framework.permissions import BasePermissionMetaclass 
from rest_framework.request import Request
from django.contrib.auth import get_user_model
# from auth.utils import fetch_user
from dataclasses import dataclass
from typing import List
# from users.views.auth import AuthenticateUser
User = get_user_model()




class CustomBasePermission(metaclass=BasePermissionMetaclass):
    """
    A base class from which all permission classes should inherit.
    """
    def has_permission(self, request:Request, view):
        """
        Return `True` if permission is granted, `False` otherwise.
        """
        return True

    def has_object_permission(self, request:Request, view, obj):
        """
        Return `True` if permission is granted, `False` otherwise.
        """
        return True

    def filter_objects_by(self ,  *args , **kwargs):
        """
        Return `dict` of Model kwargs filter .
        """
        return {}

    def exclude_objects_by(self, *args , **kwargs):
        """
        Return `dict` of Model kwargs exclude .
        """
        return {}



