class PrivateResponseMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        response=self.get_response(request)
        if getattr(request,"user",None) and request.user.is_authenticated:
            response["Cache-Control"]="no-store"
        response["Referrer-Policy"]="same-origin"
        response["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        return response
