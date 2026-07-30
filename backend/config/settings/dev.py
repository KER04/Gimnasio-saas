"""Settings de desarrollo."""

from .base import *  # noqa: F401,F403

DEBUG = True

# '.localhost' (con el punto inicial) matchea tanto 'localhost' como
# cualquier subdominio suyo ('gimx.localhost', 'gimb.localhost', ...) --
# ver Django `is_same_domain`. Los navegadores modernos resuelven
# *.localhost a 127.0.0.1 sin tocar /etc/hosts ni DNS, así que en desarrollo
# el admin de Django (Parte C2) se prueba entrando por
# http://<subdominio>.localhost:8000/admin/, exactamente como en producción
# se entraría por http://<subdominio>.tuapp.com/admin/.
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '.localhost']
