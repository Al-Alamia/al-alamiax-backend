from rest_framework.views import APIView
from permissions.models import CustomBasePermission 
from rest_framework.serializers import ModelSerializer
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from typing import List , Dict
from .parser import RequestParser
from django.db.models import Model
from django.db.models import QuerySet
from .exceptions import CreationFaildException, UpdateFaildException


class APIViewMixins(APIView):
    permission_classes:List[CustomBasePermission] = []
    allowed_methods = ["GET","POST","PUT","DELETE"]
    pagination_class:PageNumberPagination = None
    model:Model = None
    model_serializer:ModelSerializer = None
    order_by:List = []
    search_filters:List[str] = ["uuid","username"]
    creating_filters:List[str] = ["*"]
    requiered_fields:List[str] = []
    updating_filters:List[str] = ["*"]
    unique_field:str = 'id'
    permissions_config = {}

    def _get(self,request:Request):
        parser = RequestParser( request , self.search_filters)
        queryset = self.model.objects.filter(**parser.params).all().distinct().order_by(*self.order_by)
        queryset = self.filter_queryset_with_permissions(queryset)
        if self.pagination_class :
            return self.get_pagination_data(queryset,request)
        return self.model_serializer(queryset , many=True).data


    def _post(self,request:Request):
        serializer:ModelSerializer = self.model_serializer(data = request.data)
        if serializer.is_valid():
            serializer.save()
            return serializer.data
        else :
            raise CreationFaildException("Creation Faild" , serializer.errors )


    def _put(self,request:Request):
        id = request.query_params.get(self.unique_field)
        queryset = self.model.objects.filter(**{self.unique_field:id})
        queryset = self.filter_queryset_with_permissions(queryset)
        obj = queryset.get(**{self.unique_field:id})
        data = request.data.copy()
        if "picture" in request.FILES.keys():
            obj.picture = request.FILES['picture']
            obj.save()            
        serializer:ModelSerializer = self.model_serializer(instance=obj , data = data , partial=True)
        setattr(serializer.instance,"__by",request.user)
        if serializer.is_valid():
            serializer.save()
            return serializer.data
        else :
            raise UpdateFaildException("Update Faild" , serializer.errors) 


    def _delete(self , request:Request ):
        id = request.query_params.get(self.unique_field)
        queryset = self.model.objects.filter(**{self.unique_field:id})
        queryset = self.filter_queryset_with_permissions(queryset)
        obj = queryset.get(**{self.unique_field:id})
        data = self.model_serializer(obj).data
        obj.delete()
        return data
        

 
    def filter_queryset_with_permissions(self,queryset:QuerySet)->QuerySet:
        filter_kwargs = {}
        exclode_kwargs = {}
        for perm_class in self.permission_classes :
            perm_class = perm_class() 
            filter_objects_by = getattr(perm_class,"filter_objects_by",lambda : {})
            exclude_objects_by = getattr(perm_class,"exclude_objects_by",lambda : {})
            filter_kwargs.update(filter_objects_by().get(self.model.__name__,{}))#.get(user.role,{}))
            exclode_kwargs.update(exclude_objects_by().get(self.model.__name__,{}))#.get(user.role,{}))
        return queryset.filter(**filter_kwargs).exclude(**exclode_kwargs)
        

    def get_pagination_data(self,queryset:QuerySet,request:Request):
        paginator = self.pagination_class()
        result = paginator.paginate_queryset(queryset,request)
        return {
            'total_count': queryset.count() ,
            'count': len(result) if result else 0 ,
            'next':paginator.get_next_link(),
            'previous':paginator.get_previous_link(),
            "results": self.model_serializer( result , many=True ).data
        }


    def get_permissions(self):
        self.permission_classes = self.permissions_config.get(str(self.request.method),[])
        return [permission() for permission in self.permission_classes]
