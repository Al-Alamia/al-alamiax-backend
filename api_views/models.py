from .mixin import APIViewMixins
# from utils.decorator import handle_errors
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK,HTTP_400_BAD_REQUEST,HTTP_405_METHOD_NOT_ALLOWED
from rest_framework.request import Request
from .exceptions import CreationFaildException , ExaptionBase



class APIViewSet(APIViewMixins):

        
    def get(self,request:Request):
        return self.wrapper(self._get,request=request)
        # return Response(self._get(request=request))


    def post(self,request:Request):
        return self.wrapper(self._post,request=request)
        # return Response(self._post(request=request))


    def put(self,request:Request):
        return self.wrapper(self._put,request=request)
        # return Response(self._put(request=request))

    def delete(self,request:Request):
        return self.wrapper(self._delete,request=request)
        # return Response(self._delete(request=request))

    def wrapper( self, func, *args, **kwargs):
        request = kwargs.get("request")
        if request.method in self.allowed_methods :
            try:
                data = func(*args, **kwargs)
                if isinstance(data,Response):
                    return data
                response = Response(data, HTTP_200_OK)

            except CreationFaildException as e:
                data = {
                    "details": e.args[1],
                    "type": str(e.__class__.__name__),
                }
                response = Response(data, HTTP_400_BAD_REQUEST)

            except ExaptionBase as e:
                data = {
                    "details": str(e),
                    "type": str(e.__class__.__name__),
                }
                response = Response(data, HTTP_400_BAD_REQUEST)
        else :
            data = {
                "detail": f"Method \"{request.method}\" not allowed."
            }
            response = Response(data, HTTP_405_METHOD_NOT_ALLOWED)
        return response





class Field():
    def __init__(self, field_name, field_model, field_get_by , **kwargs):
        self.field_name = field_name
        self.field_model = field_model
        self.field_get_by = field_get_by

    def __str__(self):
        return f"{self.field_name} - {self.field_model} - {self.field_get_by}"


class ForeignField(Field):
    """
    This class represents a foreign field.
    """
    
    def get_value(self,value):
        if value :
            return self.field_model.objects.get(**{self.field_get_by:value})
        return None
    def to_dict(self,value):
        return {
            self.field_name:self.get_value(value),
        }
    
class ManyToManyField(Field):
    """
    This class represents a many to many field.
    """
    
    def get_values(self,values:list):
        return self.field_model.objects.filter(**{f"{self.field_get_by}__in":values})    
    
    def add_to_model(self,instance,values:list):
        values = self.get_values(values)
        field = getattr(instance,self.field_name)
        for value in values:
            field.add(value)

    def set_to_model(self,instance,values:list):
        values = self.get_values(values)
        field = getattr(instance,self.field_name)
        field.set(values)
