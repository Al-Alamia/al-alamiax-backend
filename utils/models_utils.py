import os , re
from django.core.exceptions import ValidationError
from apps.users.types import UserTypes

SAOUDI_NUMBER_REGEX = r"^[\+]?(?:966|0)(5\d{8})$"
EGYPTION_NUMBER_REGEX = r"^0(11|12|10|15)(\d{8})$"


def image_upload_path(instance, filename):
    # Define the directory to save the image file
    upload_to = f'profile-photos/'

    # Get the file extension from the original filename
    ext = filename.split('.')[-1]
    # Rename the image file with a unique name using instance.pk or other identifier
    filename = f'{instance.user}-{instance.uuid}.{ext}'  
    # Return the full path to save the image file
    return os.path.join(upload_to,str(instance.user), filename)


    
    
def validate_lead_number(number:str):
    resault = re.match(SAOUDI_NUMBER_REGEX,number)
    if resault :
        return f"+966{resault.group(1)}"  
    raise ValidationError("""Number Doesn't match +9665XXXXXXXX or 9665XXXXXXXX or 05XXXXXXXX""")


def validate_user_number(number:str):
    resault = re.match(EGYPTION_NUMBER_REGEX,number)
    if resault :
        return f"{resault.string}"
    raise ValidationError("""Number Doesn't match +20XXXXXXXXXX or 0XXXXXXXXXX """)


def validate_role(role:str):
    roles = list(map(lambda t : t[0] ,UserTypes.choices))
    if role not in roles:
        raise ValidationError(f"""Role Doesn't match any of these values ( {" ,".join(roles)} ) """)