import json
from kafka import KafkaProducer
from datetime import datetime

try:
    producer = KafkaProducer(
        bootstrap_servers=['localhost:9092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        api_version_auto_timeout_ms=2000
    )
except Exception as e:
    print(f"⚠️ Advertencia: No se pudo conectar a Kafka al iniciar. Las alertas no se enviarán. Detalle: {e}")
    producer = None

def publicar_evento(topic: str, evento: dict):
    if not producer:
        print(f"Topic: {topic} | Evento: {evento}")
        return

    try:
        evento['timestamp'] = datetime.utcnow().isoformat()
        producer.send(topic, value=evento)
        producer.flush()
    except Exception as e:
        print(f"Error al publicar en '{topic}': {e}")