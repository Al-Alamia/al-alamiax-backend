from django.http.request import HttpRequest






def fetch_user(request:HttpRequest , auth_class):
    user , token = auth_class(request)
    if all(var != None for var in [user , token]):
        return user
    else :
        return None
