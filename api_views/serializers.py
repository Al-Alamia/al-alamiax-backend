from rest_framework.serializers import  ModelSerializer 
import typing
from .models import  ForeignField , ManyToManyField


class ModelSerializer(ModelSerializer):
    class Meta:
        foreign_models:typing.Dict[str,ForeignField]
        many_to_many_models:typing.Dict[str,ManyToManyField]

    def run_validation(self, data:dict=...):
        self._foreign_models = {}
        self._many_to_many_models = {}
        [ 
            self._foreign_models.update(foreign_model.to_dict(data.get(foreign_model.field_name))) 
            for  key , foreign_model in getattr(self.Meta,"foreign_models",{}).items() 
        ]
        [
            self._many_to_many_models.update({key:many_to_many_model.get_values(data.get(many_to_many_model.field_name,[]))}) 
            for key , many_to_many_model in getattr(self.Meta,"many_to_many_models",{}).items() 
        ]
        return super().run_validation(data)
    
    def create(self, validated_data:dict , *args , **kwargs):
        validated_data.update(self._foreign_models)
        validated_data.update(self._many_to_many_models)
        return super().create(validated_data)

    def update(self, instance, validated_data:dict):
        validated_data.update(self._foreign_models)
        validated_data.update(self._many_to_many_models)
        return super().update(instance, validated_data)