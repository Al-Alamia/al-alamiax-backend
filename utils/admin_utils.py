from typing import List , Tuple


class FieldSets(object):
    def __init__(self , sections:List[str] , sections_fields:List[Tuple]) -> None:
        self.__sections = sections
        self.__sections_fields = sections_fields

    @property
    def fieldsets(self)-> str:
        return self.create_sections([self.add_section(name,fields) for name , fields in zip(self.__sections,self.__sections_fields) ])

    def add_section(self,name:str , fields:List[str]):
        return [name , {"fields":fields}]

    def create_sections(self,sections:Tuple[str,dict]):
        return [section for section in sections]

