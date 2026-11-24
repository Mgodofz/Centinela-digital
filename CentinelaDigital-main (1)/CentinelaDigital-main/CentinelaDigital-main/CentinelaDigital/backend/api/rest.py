from flask import Blueprint, jsonify, request
from database.bd import obtener_conexion

api_bp = Blueprint('api', __name__, url_prefix='/api')


# ---------- HELPERS ----------
def _row(r):
    """Convierte filas DictCursor a JSON serializable (fechas -> str)."""
    if r is None:
        return None
    return {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in r.items()}


def _rows(rs):
    return [_row(r) for r in rs]


# ---------- REPORTES ----------
@api_bp.get('/reportes')
def get_reportes():
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("""
                SELECT r.id, r.incidente, r.fecha,
                       e.nivel_riesgo, e.prioridad,
                       ca.estatus_caso, ca.responsable
                FROM reportes r
                LEFT JOIN evaluaciones e ON e.reporte_id = r.id
                LEFT JOIN casos ca ON ca.reporte_id = r.id
                ORDER BY r.id DESC
            """)
            return jsonify(_rows(c.fetchall()))
    finally:
        conexion.close()


@api_bp.get('/reportes/<int:rid>')
def get_reporte(rid):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("""
                SELECT r.*, e.nivel_riesgo, e.prioridad,
                       ca.id AS caso_id, ca.estatus_caso, ca.responsable
                FROM reportes r
                LEFT JOIN evaluaciones e ON e.reporte_id=r.id
                LEFT JOIN casos ca ON ca.reporte_id=r.id
                WHERE r.id=%s
            """, (rid,))
            r = c.fetchone()
            if not r:
                return jsonify({"error": "Reporte no encontrado"}), 404
            return jsonify(_row(r))
    finally:
        conexion.close()


@api_bp.post('/reportes')
def crear_reporte():
    data = request.get_json(silent=True) or {}
    incidente = data.get('incidente')
    nivel = data.get('nivel_riesgo', 'Baja')
    if not incidente:
        return jsonify({"error": "incidente es obligatorio"}), 400
    prioridad = {'Baja': 1, 'Media': 2, 'Alta': 3, 'Crítica': 4}.get(nivel, 1)

    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("INSERT INTO reportes (incidente) VALUES (%s)", (incidente,))
            rid = c.lastrowid
            c.execute(
                "INSERT INTO evaluaciones (reporte_id, nivel_riesgo, prioridad) VALUES (%s,%s,%s)",
                (rid, nivel, prioridad)
            )
            conexion.commit()
        return jsonify({"id": rid, "incidente": incidente,
                        "nivel_riesgo": nivel, "prioridad": prioridad}), 201
    except Exception as e:
        conexion.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conexion.close()


# ---------- CASOS ----------
@api_bp.get('/casos')
def get_casos():
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("SELECT * FROM casos ORDER BY id DESC")
            return jsonify(_rows(c.fetchall()))
    finally:
        conexion.close()


@api_bp.post('/casos')
def crear_caso():
    data = request.get_json(silent=True) or {}
    reporte_id = data.get('reporte_id')
    responsable = data.get('responsable')
    estatus = data.get('estatus_caso', 'Abierto')
    if not reporte_id or not responsable:
        return jsonify({"error": "reporte_id y responsable son obligatorios"}), 400

    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute(
                "INSERT INTO casos (reporte_id, responsable, estatus_caso) VALUES (%s,%s,%s)",
                (reporte_id, responsable, estatus)
            )
            cid = c.lastrowid
            conexion.commit()
        return jsonify({"id": cid, "reporte_id": reporte_id,
                        "responsable": responsable, "estatus_caso": estatus}), 201
    except Exception as e:
        conexion.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conexion.close()


@api_bp.put('/casos/<int:cid>')
def actualizar_caso(cid):
    data = request.get_json(silent=True) or {}
    estatus = data.get('estatus_caso')
    responsable = data.get('responsable')
    if not estatus and not responsable:
        return jsonify({"error": "nada que actualizar"}), 400

    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            campos, vals = [], []
            if estatus:
                campos.append("estatus_caso=%s"); vals.append(estatus)
            if responsable:
                campos.append("responsable=%s"); vals.append(responsable)
            vals.append(cid)
            c.execute(f"UPDATE casos SET {', '.join(campos)} WHERE id=%s", tuple(vals))
            conexion.commit()
        return jsonify({"id": cid, "actualizado": True})
    finally:
        conexion.close()


# ---------- INSTITUCIONES ----------
@api_bp.get('/instituciones')
def get_instituciones():
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("SELECT * FROM instituciones ORDER BY id DESC")
            return jsonify(_rows(c.fetchall()))
    finally:
        conexion.close()


@api_bp.post('/instituciones')
def crear_institucion():
    data = request.get_json(silent=True) or {}
    nombre = data.get('nombre_institucion')
    especialidad = data.get('especialidad')
    contacto = data.get('contacto')
    if not all([nombre, especialidad, contacto]):
        return jsonify({"error": "nombre_institucion, especialidad y contacto obligatorios"}), 400

    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute(
                "INSERT INTO instituciones (nombre_institucion, especialidad, contacto) VALUES (%s,%s,%s)",
                (nombre, especialidad, contacto)
            )
            iid = c.lastrowid
            conexion.commit()
        return jsonify({"id": iid, "nombre_institucion": nombre}), 201
    finally:
        conexion.close()


# ---------- CANALIZACIONES ----------
@api_bp.get('/canalizaciones')
def get_canalizaciones():
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("""
                SELECT ca.*, i.nombre_institucion
                FROM canalizaciones ca
                JOIN instituciones i ON i.id=ca.institucion_id
                ORDER BY ca.id DESC
            """)
            return jsonify(_rows(c.fetchall()))
    finally:
        conexion.close()


@api_bp.post('/canalizaciones')
def crear_canalizacion():
    data = request.get_json(silent=True) or {}
    reporte_id = data.get('reporte_id')
    institucion_id = data.get('institucion_id')
    if not reporte_id or not institucion_id:
        return jsonify({"error": "reporte_id e institucion_id obligatorios"}), 400

    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute(
                "INSERT INTO canalizaciones (reporte_id, institucion_id) VALUES (%s,%s)",
                (reporte_id, institucion_id)
            )
            cid = c.lastrowid
            conexion.commit()
        return jsonify({"id": cid}), 201
    finally:
        conexion.close()


# ---------- COMUNICACIONES ----------
@api_bp.get('/casos/<int:cid>/mensajes')
def get_mensajes(cid):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("SELECT * FROM comunicaciones WHERE caso_id=%s ORDER BY id", (cid,))
            return jsonify(_rows(c.fetchall()))
    finally:
        conexion.close()


@api_bp.post('/casos/<int:cid>/mensajes')
def crear_mensaje(cid):
    data = request.get_json(silent=True) or {}
    remitente = data.get('remitente')
    mensaje = data.get('mensaje')
    if not remitente or not mensaje:
        return jsonify({"error": "remitente y mensaje obligatorios"}), 400

    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute(
                "INSERT INTO comunicaciones (caso_id, remitente, mensaje) VALUES (%s,%s,%s)",
                (cid, remitente, mensaje)
            )
            mid = c.lastrowid
            conexion.commit()
        return jsonify({"id": mid}), 201
    finally:
        conexion.close()


# ---------- ESTADÍSTICAS ----------
@api_bp.get('/estadisticas')
def get_estadisticas():
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("SELECT COUNT(*) AS t FROM reportes"); total_reportes = c.fetchone()['t']
            c.execute("SELECT COUNT(*) AS t FROM usuarios"); total_usuarios = c.fetchone()['t']
            c.execute("SELECT COUNT(*) AS t FROM instituciones"); total_inst = c.fetchone()['t']
            c.execute("SELECT COUNT(*) AS t FROM casos WHERE estatus_caso='Cerrado'"); cerrados = c.fetchone()['t']
            c.execute("SELECT nivel_riesgo, COUNT(*) AS total FROM evaluaciones GROUP BY nivel_riesgo")
            riesgo = _rows(c.fetchall())
            c.execute("SELECT estatus_caso, COUNT(*) AS total FROM casos GROUP BY estatus_caso")
            estados = _rows(c.fetchall())
        return jsonify({
            "total_reportes": total_reportes,
            "total_usuarios": total_usuarios,
            "total_instituciones": total_inst,
            "cerrados": cerrados,
            "por_riesgo": riesgo,
            "por_estado": estados
        })
    finally:
        conexion.close()