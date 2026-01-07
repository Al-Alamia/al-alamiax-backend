from .models import CustomBasePermission
# from .utils import generate_perm

class IsAgent(CustomBasePermission):

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'AGENT'

    def filter_objects_by(self, *args, **kwargs):
        return {"User":{"is_superuser":False},"TargetSlice":{"is_global":False}}

    def exclude_objects_by(self, *args , **kwargs):
        return {"User":{"role":"OWNER"}}



class IsManager(CustomBasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'MANAGER'

    def filter_objects_by(self,  *args, **kwargs):
        return {"User":{"is_superuser":False},"TargetSlice":{"is_global":False}}

    def exclude_objects_by(self, *args , **kwargs):
        return {"User":{"role":"OWNER"}}



class IsHR(CustomBasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'HR'

    def filter_objects_by(self,  *args, **kwargs):
        return {"User":{"is_superuser":False},"TargetSlice":{"is_global":False}}

    def exclude_objects_by(self, *args , **kwargs):
        return {"User":{"role":"OWNER"}}



class IsOwner(CustomBasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'OWNER'
    def filter_objects_by(self,  *args, **kwargs):
        return {"User":{"is_superuser":False},"TargetSlice":{"is_global":False}}





class IsSuperUser(CustomBasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_superuser

    def filter_objects_by(self,  *args, **kwargs):
        return {"User":{}}

    def exclude_objects_by(self, *args , **kwargs):
        return {"User":{}}



class AllowAnyAuthenticated(CustomBasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def filter_objects_by(self,  *args, **kwargs):
        return {"User":{"is_superuser":False},"TargetSlice":{"is_global":False}}

    def exclude_objects_by(self, *args , **kwargs):
        return {"User":{"role":"OWNER"}}


