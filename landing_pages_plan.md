
Para diseñar una **landing page o página de acceso a modo de demostración** para el **Portal de Clientes de PortoCaribe Logística S.A.** (basado en los requerimientos del proyecto de aula para la bodega en Mamonal, Cartagena), la interfaz debe reflejar profesionalismo, agilidad y seguridad, solucionando los problemas de lentitud y visibilidad reportados por servicio al cliente.

A continuación se detallan los elementos esenciales que debe contener la demostración:

### 1. Cabecera y Autenticación Segura (Login / Acceso)

* **Branding Corporativo:** Identidad visual de *PortoCaribe Logística S.A.*, operador logístico y portuario.


* **Formulario de Inicio de Sesión:** Campos optimizados para usuario y contraseña.
* **Medidas de Seguridad Visibles:** Indicador de protocolo TLS (HTTPS) y un mensaje o mecanismo que demuestre la **limitación de intentos de inicio de sesión** (requisito clave de seguridad de la infraestructura).



### 2. Módulo Principal de Rastreo Rápido (Tracking Widget)

* **Barra de Búsqueda de Contenedores:** Un campo de entrada destacado donde el cliente pueda ingresar el número de contenedor, *Bill of Lading* (BL) o orden de despacho.
* **Indicador de Rendimiento (Simulado):** Un pequeño widget o indicador de estado de la red/servidor (conectado a la VM1 `srv-core` con Apache y PostgreSQL) que demuestre que el tiempo de respuesta es óptimo, contrastando con el problema crítico anterior donde superaba los 10 segundos con múltiples buques.



### 3. Panel de Resultados y Estado del Contenedor

Una vez realizada la consulta, la demostración debe mostrar dinámicamente:

* **Estado Actual:** (Ej. *En muelle*, *Almacenado en bodega de 12.000 m²*, *En proceso de despacho*).


* **Detalles de la Carga:** Importador/Exportador, fecha de arribo del buque y muelle asignado.
* **Línea de Tiempo (Timeline) de Trazabilidad:** Hitos del contenedor desde que llega en buque hasta que se despacha por la garita.

### 4. Sección Informativa y de Alertas Operativas

* **Avisos del Puerto:** Un panel de notificaciones para informar sobre congestión en muelles o tiempos estimados de entrega cuando operan varios buques simultáneamente.
* **Canal de Soporte Directo:** Datos de contacto o un enlace rápido con el área de atención al cliente coordinada por Liliana Támara, garantizando transparencia ante cualquier incidencia.



---
