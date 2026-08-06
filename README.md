# 🏥 Sistema de Alertas y Monitoreo IoT para Adultos Mayores - Backend (Python)

Este repositorio contiene la implementación en Python del backend transaccional para el **Sistema de Monitoreo de Pacientes y Dispositivos IoT**. 

Este módulo forma parte de una arquitectura distribuida orientada a servicios, diseñada para garantizar alta disponibilidad y baja latencia en la gestión de emergencias médicas de adultos mayores. El sistema captura eventos en tiempo real (como el pulso o caídas detectadas por el acelerómetro) a través de dispositivos wearables y los procesa para notificar al personal de salud.

## 🏗️ Arquitectura del Sistema
El proyecto implementa una arquitectura orientada a servicios dividida en múltiples capas:
*   **API Gateway:** Nginx (encargado de redirigir las peticiones HTTP).
*   **Gestión de Identidad (IAM):** Keycloak implementado con roles específicos (`nurse` y `administrator`) y validación de tokens JWT.
*   **Broker de Mensajería:** Integración dual utilizando MQTT (Mosquitto) para la captura local de eventos IoT, y Apache Kafka para la gestión global de eventos del backend.

## ⚙️ Servicios Implementados
Este backend expone interfaces RESTful (CRUD) y aplica las reglas de negocio para las siguientes entidades:
*   **Servicio de Pacientes:** Gestión de datos demográficos, historial de alergias, condiciones médicas y contactos de emergencia.
*   **Servicio de Dispositivos (Wearables):** Trazabilidad de dispositivos IoT, estado de conexión (dirección MAC) y monitoreo de niveles de batería.
*   **Servicio de Alertas:** Clasificación y enrutamiento de emergencias dependiendo del tipo, nivel y estado, manteniendo la trazabilidad histórica.
*   **Servicio de Habitaciones:** Asignación y control de ubicación por pisos, pabellones y número de cuarto.
*   **Servicio de Tipos de Alerta:** Configuración de códigos y descripciones para la tipificación de emergencias.

## 🛠️ Instalación y Configuración Local

1. Clona este repositorio:
   ```bash
   git clone [https://github.com/NicolasT08/back-python.git](https://github.com/NicolasT08/back-python.git)
   cd back-python
