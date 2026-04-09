import os
import pytest

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

from app import create_app, db

# MOTOR DE FLASK Y BASE DE DATOS
@pytest.fixture
def app():

    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"
    })
    
    with app.app_context():
        db.create_all()
        yield app  
        db.session.remove()
        db.drop_all() 

# SIMULADOR DE KEYCLOAK
@pytest.fixture
def mock_auth_token(mocker):
    """
    Esta función engaña al decorador @token_required.
    Evita que intente conectarse al servidor real de Keycloak.
    """
    def _mock_token(rol):

        mocker.patch('app.auth.keycloak_openid.public_key', return_value="llave_publica_falsa")
        
        mocker.patch('app.auth.keycloak_openid.decode_token', return_value={
            "preferred_username": "usuario_prueba",
            "realm_access": {
                "roles": [rol]
            }
        })
    return _mock_token

# PRUEBAS DE SEGURIDAD ESTRICTA (RBAC)
@pytest.mark.parametrize("metodo, ruta", [
    ("POST", "/patient"),               # Crear paciente
    ("PUT", "/patient/uuid-123"),       # Editar paciente
    ("DELETE", "/patient/uuid-123"),    # Borrar paciente
    ("POST", "/device"),                # Crear dispositivo
    ("PUT", "/device/uuid-123"),        # Editar dispositivo
    ("DELETE", "/device/uuid-123"),     # Borrar dispositivo
    ("POST", "/room"),                  # Crear habitación
    ("PUT", "/room/uuid-123"),          # Editar habitación
    ("DELETE", "/room/uuid-123"),       # Borrar habitación
    ("DELETE", "/alert/uuid-123"),      # Borrar alerta
    ("POST", "/alert-type"),            # Crear tipo de alerta
    ("PUT", "/alert-type/uuid-123"),    # Editar tipo de alerta
    ("DELETE", "/alert-type/uuid-123")  # Borrar tipo de alerta
])
def test_enfermero_bloqueado_en_rutas_admin(client, mock_auth_token, metodo, ruta):
    """
    Escenario: Un usuario con rol 'nurse' intenta acceder a rutas exclusivas de 'administrator'.
    El sistema debe rechazar la petición con un error 403 (Forbidden).
    """
    mock_auth_token("nurse")
    
    payload_falso = {"data": "intento_de_hackeo"}
    headers = {"Authorization": "Bearer token_falso"}
    
    if metodo == "POST":
        response = client.post(ruta, json=payload_falso, headers=headers)
    elif metodo == "PUT":
        response = client.put(ruta, json=payload_falso, headers=headers)
    elif metodo == "DELETE":
        response = client.delete(ruta, headers=headers)
        
    assert response.status_code == 403
    assert "Acceso denegado" in response.get_json()["error"]


def test_enfermero_acceso_permitido_a_lectura(client, mock_auth_token):
    """
    Escenario: Validar que el enfermero SÍ pueda consultar datos (GET), 
    ya que para eso sí tiene permisos.
    """
    mock_auth_token("nurse")
    response = client.get("/patient", headers={"Authorization": "Bearer token_falso"})
    assert response.status_code == 200


# PRUEBAS DE CAMINO FELIZ E INTEGRACIÓN (KAFKA)
def test_admin_puede_crear_habitacion(client, mock_auth_token):

    # 1. Simulamos ser administradores
    mock_auth_token("administrator")
    
    # 2. Enviamos los datos de una habitación nueva
    payload_habitacion = {
        "floor": 3,
        "roomNumber": "305",
        "roomPavilion": "Sur"
    }
    
    response = client.post("/room", json=payload_habitacion, headers={"Authorization": "Bearer token_valido"})
    
    # 3. Validamos que la respuesta sea 201 (Created) y nos devuelva un ID
    assert response.status_code == 201
    assert "roomId" in response.get_json()
    assert response.get_json()["Message"] == "Habitación registrada exitosamente"


def test_creacion_de_alerta_dispara_evento_kafka(client, mock_auth_token, mocker):
    """
    Escenario: Al registrar una emergencia, el sistema no solo guarda en BD,
    sino que obligatoriamente DEBE notificar al sistema de monitoreo vía Kafka.
    """
    from datetime import datetime, timezone

    mock_auth_token("nurse")
    
    # 1. Espiamos a Kafka
    espia_kafka = mocker.patch('app.routes.publicar_evento')
    
    # 2. Bloqueamos las operaciones de base de datos
    mocker.patch('app.routes.db.session.add')
    mocker.patch('app.routes.db.session.commit')
    
    # Simulamos el modelo Alert para que tenga una fecha válida
    # y así evitamos el error de 'NoneType' al llamar a .isoformat()
    mock_alerta = mocker.patch('app.routes.Alert')
    mock_alerta.return_value.alertId = "uuid-alerta-falsa"
    mock_alerta.return_value.createdAt = datetime.now(timezone.utc)
    
    payload_alerta = {
        "patientId": "paciente-falso-123",
        "wearableId": "manilla-falsa-456",
        "alertType": "tipo-caida",
        "alertLevel": "roja",
        "alertStatus": "activa"
    }
    
    # 4. El enfermero registra la alerta
    response = client.post("/alert", json=payload_alerta, headers={"Authorization": "Bearer token_valido"})
    
    # 5. Validamos que la petición fue exitosa
    assert response.status_code == 201
    
    # 6. Validamos que Kafka fue llamado y al tópico correcto
    espia_kafka.assert_called_once()
    argumentos_llamada, _ = espia_kafka.call_args
    assert argumentos_llamada[0] == "alertas.emergencias"