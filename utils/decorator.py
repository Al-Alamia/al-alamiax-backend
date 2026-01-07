from functools import wraps
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK,HTTP_400_BAD_REQUEST

def handle_errors(status_on_faild=HTTP_400_BAD_REQUEST , status_on_success=HTTP_200_OK,*decorator_args, **decorator_kwargs):
    def decorator(func ,*args, **kwargs):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                data = func(*args, **kwargs)
                response = Response(data, status_on_success)
            except Exception as e:
                data = {
                    "message": str(e),
                    "type": str(e.__class__.__name__)
                }
                response = Response(data, status_on_faild)
            return response
        return wrapper
    return decorator


from functools import wraps
from django.http import JsonResponse

def custom_decorator(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Add custom logic here
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        # Call the original view function
        return view_func(request, *args, **kwargs)
    
    return wrapper
