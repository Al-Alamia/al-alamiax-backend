from rest_framework.request import Request
from typing import Dict  , List
import json
# from django.db.models import Model
# from .constants import GET_MODEL_KEY_NAME ,MODEL_KEY_NAME , VALUE_KEY_NAME

class RequestParser(object):
    
    def __init__(self, request:Request , available_filters:list , foreign_models_names:List[str]=[] , many_to_many_models_names:List[str]={} ) -> None:
        self._request = request
        self._available_filters = available_filters
        self._foreign_models_names = foreign_models_names
        self._many_to_many_models_names = many_to_many_models_names
        if isinstance(self._request.body,dict):
            self.__body = self.__parse(self._available_filters,self._request.body.copy())
        elif isinstance(self._request.body,bytes) and self._request.body:
            try : 
                data = json.loads(self._request.body)
            except json.JSONDecodeError: 
                data = self._request.data
            self.__body = self.__parse(self._available_filters,data)
        else :
            self.__body = {}

        self.__foreign_models = self.__parse(self._foreign_models_names,self.body,True)
        self.__many_to_many_models = self.__parse(self._many_to_many_models_names,self.body,True)
        
    @property
    def body(self)->dict:
        return self.__body
        

    @property
    def params(self):
        return self.__parse(self._available_filters,self._request.query_params.dict().copy()) 

    @property
    def foreign_models(self):
        return self.__foreign_models

    @property
    def many_to_many_models(self):
        return self.__many_to_many_models

    def __parse(self,fields:List[str],parse_from:dict , pop_items:bool=False):
        if "*" in fields :
            return parse_from 
        filters = list(filter(lambda x : x.split('__')[0] in fields,parse_from.keys()))
        if pop_items :
            return {key: parse_from.pop(key) for key in filters }
        return {key: parse_from[key] for key in filters }
