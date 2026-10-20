from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import LoginSerializer, UsuarioSerializer


class LoginView(TokenObtainPairView):
    """POST /api/auth/login/ com {"username": "...", "password": "..."}."""

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]


class EuView(APIView):
    """GET /api/auth/eu/: devolve quem é o dono do token."""

    def get(self, request):
        return Response(UsuarioSerializer(request.user).data)
