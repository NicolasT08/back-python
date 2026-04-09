from functools import wraps
from flask import request, jsonify
from keycloak import KeycloakOpenID
from .kafka_producer import publicar_evento

keycloak_openid = KeycloakOpenID(
    server_url="http://localhost:8082",
    client_id="backend-python",
    realm_name="ProyectoAncianato",
    client_secret_key="ODYrpgpMzjZblJRVx3cnHGof5MqbcnsR"
)

def tiene_rol(token_info, roles_permitidos):
    try:
        roles_usuario = token_info["realm_access"]["roles"]
        return any(rol in roles_usuario for rol in roles_permitidos)
    except KeyError:
        return False

def token_required(roles_permitidos):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth_header = request.headers.get('Authorization', None)
            if not auth_header:
                return jsonify({"error": "Token requerido"}), 401

            try:
                token = auth_header.split(" ")[1]
                llave_publica = f"-----BEGIN PUBLIC KEY-----\n{keycloak_openid.public_key()}\n-----END PUBLIC KEY-----"
                opciones = {
                    "verify_signature": True, 
                    "verify_aud": False, 
                    "verify_exp": True
                }
                userinfo = keycloak_openid.decode_token(token, key=llave_publica, options=opciones)
            except Exception as e:
                print(f"⚠️ Error real al decodificar token: {str(e)}")
                publicar_evento("seguridad.accesos", {
                    "tipo": "token_invalido",
                    "endpoint": request.path,
                    "ip": request.remote_addr,
                    "error": str(e)
                })
                return jsonify({"error": "Token inválido o expirado", "detalle": str(e)}), 401

            if not tiene_rol(userinfo, roles_permitidos):
                return jsonify({"error": f"Acceso denegado: se requiere uno de estos roles: {roles_permitidos}"}), 403

            return f(userinfo, *args, **kwargs)
        return decorated
    return decorator