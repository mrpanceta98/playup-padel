# PlayUp Padel

MVP de app competitiva y gamificada de ligas amateur de padel por parejas, con progresion individual.

## Ejecutar

```bash
python3 -m backend.server
```

Abre `http://127.0.0.1:4173/`.

Credenciales demo:

- Jugador: `aitor.martin@demo.playup` / `demo123`
- Admin: `admin@playup.local` / `admin123`

## Incluye

- Backend Python sin dependencias externas.
- Base de datos SQLite (`playup.sqlite3`).
- Autenticacion por token firmado.
- Modelos principales: usuarios, perfiles, ubicaciones, clubs, niveles, divisiones, grupos, temporadas, partidos 2v2, resultados por equipos, ranking individual, historico, rating, XP, logros, avatar, Playtomic y admin reviews.
- Servicios separados para competicion, agrupacion, rating y gamificacion.
- Clasificacion mensual con limite de 10 partidos, puntos, set average, game average, fuerza de rivales, enfrentamiento directo y menor numero de partidos.
- Cierre mensual con ascensos, descensos, historico y regeneracion de grupos.
- Rating interno tipo ELO individual usando la media de rating de cada pareja.
- XP, niveles e insignias iniciales por jugador.
- UI inicial para registro, perfil, mi liga, partidos, ranking, progresion, avatar, logros, Playtomic y admin.
- Logo oficial en `assets/playup-logo.png`.
- Retos: abiertos, automaticos por rating similar, formato pareja opcional, retos semanales, notificaciones, XP e insignias.
- Activacion de jugadores: Jugar ahora, estado Disponible para jugar, Busco partido, jugadores activos en las ultimas 48h y creacion rapida de propuesta 2v2.

## Partidos 2v2

- Cada partido tiene Equipo A y Equipo B, con dos jugadores por equipo.
- El marcador se introduce por equipos.
- Cada jugador de la pareja ganadora recibe 3 puntos.
- Cada jugador de la pareja perdedora recibe 1 punto, o 0 si hay no presentado/abandono injustificado.
- Set average y game average se aplican individualmente usando los sets/juegos de la pareja.
- El limite de 10 partidos mensuales se aplica por jugador.
- La confirmacion debe hacerla al menos un jugador de la pareja rival.
- XP y rating se actualizan para los 4 jugadores cuando el resultado queda confirmado.

## Activacion

- `Jugar ahora` propone 1 companero y hasta 3 rivales recomendados.
- `Crear partido` genera una propuesta 2v2 desde esas recomendaciones.
- `Estoy disponible` abre automaticamente una solicitud `Busco partido`.
- Otros jugadores del grupo pueden unirse a una solicitud abierta.
- La Home muestra quienes han estado activos en las ultimas 48h y marca quien esta disponible para jugar.

## Grupos locales

- Los grupos se crean por division con maximo 30 jugadores y reparto equilibrado.
- 1-30 jugadores crean 1 grupo; 31-60 crean 2; 61-90 crean 3, y asi sucesivamente.
- El repartidor evita grupos descompensados como 30/10 y prefiere tamanos similares.
- La ordenacion prioriza region, ciudad y cercania aproximada; dentro de esa zona usa rating para evitar mezclar extremos.
- Si una division ya tiene partidos, retos o solicitudes activas, el sistema evita mover jugadores hasta el reajuste mensual.
- Los nombres siguen el formato `3a Local Grupo A`, `3a Local Grupo B`, `3a Local Grupo C`.

## Jerarquia competitiva

Todos los jugadores nuevos empiezan en `3a Local`, la division mas baja del sistema.

Orden de menor a mayor:

1. `3a Local`
2. `2a Local`
3. `1a Local`
4. `5a Regional`
5. `4a Regional`
6. `3a Regional`
7. `2a Regional`
8. `1a Regional`
9. `7a Nacional`
10. `6a Nacional`
11. `5a Nacional`
12. `4a Nacional`
13. `3a Nacional`
14. `2a Nacional`
15. `1a Nacional`

## Pruebas

```bash
python3 -m compileall backend tests
python3 -m unittest discover -s tests -v
node --check frontend/main.js
```

## App móvil con Capacitor

La app está preparada para generar builds nativas con Capacitor:

- `appId`: `com.playuppadel.app`
- `appName`: `PlayUp Padel`
- `webDir`: `dist`
- API remota configurable con `PLAYUP_API_BASE_URL`

Preparar bundle móvil:

```bash
PLAYUP_API_BASE_URL=https://api.playuppadel.com npm run mobile:prepare
```

Generar proyectos nativos:

```bash
npm install
npx cap add android
npx cap add ios
npm run cap:sync
```

Guía completa: `docs/mobile-release.md`.

Distribución beta gratuita con APK debug y PWA iPhone: `docs/beta-distribution.md`.

## Despliegue backend

Render/Railway pueden arrancar el backend con:

```bash
python3 -m backend.server
```

El servicio lee `PORT` como puerto principal, expone `/api/status` como healthcheck público y permite CORS para Capacitor/PWA con `PLAYUP_ALLOWED_ORIGINS`.

Archivos incluidos:

- `requirements.txt`
- `Procfile`
- `render.yaml`
