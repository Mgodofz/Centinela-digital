import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
from database.bd import obtener_conexion

# --- IMPORTS DE LAS APIS ---
from api import api_bp
from api.graphql_schema import schema
from ariadne import graphql_sync
from ariadne.explorer import ExplorerGraphiQL
# ------------------------------------

# Configuración de rutas (Estructura backend/frontend)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')
STATIC_DIR = os.path.join(BASE_DIR, 'frontend', 'static')
UPLOAD_DIR = os.path.join(STATIC_DIR, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, template_folder=FRONTEND_DIR, static_folder=STATIC_DIR)
app.secret_key = 'centinela-digital-2025-secret'

# --- CONEXIÓN DE LA API REST ---
app.register_blueprint(api_bp)

# --- CONEXIÓN DE GRAPHQL (ARIADNE) ---
explorer_html = ExplorerGraphiQL().html(None)

@app.route("/graphql", methods=["GET"])
def graphql_explorer():
    return explorer_html, 200

@app.route("/graphql", methods=["POST"])
def graphql_server():
    data = request.get_json()
    success, result = graphql_sync(
        schema,  # <-- Aquí ya se pasa el esquema nativo de Ariadne sin errores
        data,
        context_value={"request": request},
        debug=app.debug
    )
    status_code = 200 if success else 400
    return jsonify(result), status_code
# ------------------------------------


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('usuario_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('rol') != 'admin':
            return redirect(url_for('inicio'))
        return f(*args, **kwargs)
    return wrapper


# ---------- PÚBLICAS ----------
@app.route('/')
def inicio():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("SELECT COUNT(*) AS t FROM reportes"); reportes = c.fetchone()['t']
        c.execute("SELECT COUNT(*) AS t FROM instituciones"); inst = c.fetchone()['t']
        c.execute("SELECT COUNT(*) AS t FROM casos WHERE estatus_caso='Cerrado'"); cerr = c.fetchone()['t']
    conexion.close()
    return render_template('dashboard_inicio.html',
                           total_reportes=reportes, total_instituciones=inst, cerrados=cerr)


# ---------- AUTH ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form['correo']
        password = request.form['password']
        conexion = obtener_conexion()
        with conexion.cursor() as c:
            c.execute("SELECT * FROM usuarios WHERE correo=%s AND password=%s", (correo, password))
            u = c.fetchone()
        conexion.close()
        if u:
            session['usuario_id'] = u['id']
            session['nombre'] = u['nombre']
            session['rol'] = u.get('rol') or ('admin' if correo.lower().startswith('admin') else 'user')
            return redirect(url_for('panel_reportes') if session['rol'] == 'admin' else url_for('mis_reportes'))
        return render_template('login.html', error='Correo o contraseña incorrectos')
    return render_template('login.html')


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form['nombre']
        correo = request.form['correo']
        password = request.form['password']
        conexion = obtener_conexion()
        try:
            with conexion.cursor() as c:
                c.execute(
                    "INSERT INTO usuarios (nombre, correo, password) VALUES (%s,%s,%s)",
                    (nombre, correo, password)
                )
                conexion.commit()
        except Exception:
            conexion.close()
            return render_template('registro.html',
                                   error='Ese correo ya está registrado. Prueba con otro.')
        conexion.close()
        return redirect(url_for('login'))
    return render_template('registro.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))


# ---------- REPORTES ----------
@app.route('/nuevo-reporte', methods=['GET', 'POST'])
@login_required
def nuevo_reporte():
    if request.method == 'POST':
        incidente = request.form['incidente']
        nivel = request.form.get('nivel_riesgo', 'Baja')
        prioridad = {'Baja': 1, 'Media': 2, 'Alta': 3, 'Crítica': 4}.get(nivel, 1)
        conexion = obtener_conexion()
        try:
            with conexion.cursor() as c:
                c.execute("INSERT INTO reportes (incidente) VALUES (%s)", (incidente,))
                rid = c.lastrowid
                c.execute("INSERT INTO evaluaciones (reporte_id, nivel_riesgo, prioridad) VALUES (%s,%s,%s)",
                          (rid, nivel, prioridad))
                conexion.commit()
        finally:
            conexion.close()
        flash('Reporte registrado correctamente', 'exito')
        return redirect(url_for('mis_reportes'))
    return render_template('nuevo_reporte.html')


@app.route('/mis-reportes')
@login_required
def mis_reportes():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("""
            SELECT r.*, e.nivel_riesgo, ca.estatus_caso
            FROM reportes r
            LEFT JOIN evaluaciones e ON e.reporte_id = r.id
            LEFT JOIN casos ca ON ca.reporte_id = r.id
            ORDER BY r.id DESC
        """)
        reportes = c.fetchall()
    conexion.close()
    pendientes = sum(1 for r in reportes if not r.get('estatus_caso'))
    en_proceso = sum(1 for r in reportes if r.get('estatus_caso') == 'Abierto')
    resueltos = sum(1 for r in reportes if r.get('estatus_caso') == 'Cerrado')
    return render_template('mis_reportes.html', reportes=reportes,
                           pendientes=pendientes, en_proceso=en_proceso, resueltos=resueltos)


@app.route('/reporte/<int:rid>', methods=['GET', 'POST'])
@login_required
def detalle_reporte(rid):
    conexion = obtener_conexion()
    if request.method == 'POST':
        mensaje = request.form['mensaje']
        with conexion.cursor() as c:
            c.execute("SELECT id FROM casos WHERE reporte_id=%s", (rid,))
            caso = c.fetchone()
            if caso:
                c.execute("INSERT INTO comunicaciones (caso_id, remitente, mensaje) VALUES (%s,%s,%s)",
                          (caso['id'], session['nombre'], mensaje))
                conexion.commit()
        conexion.close()
        return redirect(url_for('detalle_reporte', rid=rid))

    with conexion.cursor() as c:
        c.execute("""SELECT r.*, e.nivel_riesgo, ca.estatus_caso, ca.id AS caso_id
                     FROM reportes r
                     LEFT JOIN evaluaciones e ON e.reporte_id=r.id
                     LEFT JOIN casos ca ON ca.reporte_id=r.id
                     WHERE r.id=%s""", (rid,))
        reporte = c.fetchone()
        c.execute("""SELECT c.* FROM comunicaciones c
                     JOIN casos ca ON ca.id=c.caso_id
                     WHERE ca.reporte_id=%s ORDER BY c.id""", (rid,))
        comunicaciones = c.fetchall()
        c.execute("""SELECT d.* FROM documentos_evidencia d
                     JOIN casos ca ON ca.id=d.caso_id
                     WHERE ca.reporte_id=%s""", (rid,))
        evidencias = c.fetchall()
        c.execute("SELECT 1 FROM canalizaciones WHERE reporte_id=%s LIMIT 1", (rid,))
        canalizado = c.fetchone()
        c.execute("""SELECT i.nombre_institucion FROM canalizaciones cn
                     JOIN instituciones i ON i.id=cn.institucion_id
                     WHERE cn.reporte_id=%s LIMIT 1""", (rid,))
        inst = c.fetchone()
    conexion.close()
    if not reporte:
        return redirect(url_for('mis_reportes'))
    return render_template('detalle_reporte.html', reporte=reporte,
                           comunicaciones=comunicaciones, evidencias=evidencias,
                           canalizado=bool(canalizado),
                           institucion=inst['nombre_institucion'] if inst else None)


# ---------- ADMIN ----------
@app.route('/panel')
@admin_required
def panel_reportes():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("""SELECT r.*, e.nivel_riesgo, ca.estatus_caso
                     FROM reportes r
                     LEFT JOIN evaluaciones e ON e.reporte_id=r.id
                     LEFT JOIN casos ca ON ca.reporte_id=r.id
                     ORDER BY r.id DESC""")
        reportes = c.fetchall()
        total = len(reportes)
        criticos = sum(1 for r in reportes if r.get('nivel_riesgo') == 'Crítica')
        abiertos = sum(1 for r in reportes if r.get('estatus_caso') == 'Abierto')
        cerrados = sum(1 for r in reportes if r.get('estatus_caso') == 'Cerrado')
    conexion.close()
    return render_template('panel_reportes.html', reportes=reportes,
                           total=total, criticos=criticos,
                           casos_abiertos=abiertos, cerrados=cerrados)


@app.route('/casos')
@admin_required
def casos():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("SELECT * FROM casos ORDER BY id DESC")
        casos = c.fetchall()
    conexion.close()
    return render_template('casos.html', casos=casos)


@app.route('/nuevo-caso', methods=['GET', 'POST'])
@admin_required
def nuevo_caso():
    conexion = obtener_conexion()
    if request.method == 'POST':
        with conexion.cursor() as c:
            c.execute(
                "INSERT INTO casos (reporte_id, responsable, estatus_caso) VALUES (%s,%s,%s)",
                (request.form['reporte_id'], request.form['responsable'],
                 request.form.get('estatus_caso', 'Abierto'))
            )
            conexion.commit()
        conexion.close()
        return redirect(url_for('casos'))

    with conexion.cursor() as c:
        c.execute("""SELECT r.* FROM reportes r
                     WHERE r.id NOT IN (SELECT reporte_id FROM casos)
                     ORDER BY r.id DESC""")
        reportes_sin_caso = c.fetchall()
    conexion.close()
    return render_template('nuevo_caso.html', reportes_sin_caso=reportes_sin_caso)


@app.route('/caso/<int:cid>', methods=['GET', 'POST'])
@admin_required
def detalle_caso(cid):
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("SELECT * FROM casos WHERE id=%s", (cid,))
        caso = c.fetchone()
        if not caso:
            conexion.close()
            return redirect(url_for('casos'))
        c.execute("SELECT * FROM seguimiento_tiempo WHERE caso_id=%s ORDER BY id", (cid,))
        seguimiento = c.fetchall()
        c.execute("SELECT * FROM comunicaciones WHERE caso_id=%s ORDER BY id", (cid,))
        comunicaciones = c.fetchall()
        c.execute("SELECT * FROM documentos_evidencia WHERE caso_id=%s", (cid,))
        evidencias = c.fetchall()
        c.execute("SELECT * FROM cierres_retroalimentacion WHERE caso_id=%s", (cid,))
        cierre = c.fetchone()
    conexion.close()
    return render_template('detalle_caso.html', caso=caso, seguimiento=seguimiento,
                           comunicaciones=comunicaciones, evidencias=evidencias, cierre=cierre)


@app.route('/caso/<int:cid>/seguimiento', methods=['POST'])
@admin_required
def agregar_seguimiento(cid):
    comentario = request.form['comentario_avance']
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("INSERT INTO seguimiento_tiempo (caso_id, comentario_avance) VALUES (%s,%s)",
                  (cid, comentario))
        conexion.commit()
    conexion.close()
    return redirect(url_for('detalle_caso', cid=cid))


@app.route('/caso/<int:cid>/mensaje', methods=['POST'])
@admin_required
def mensaje_caso(cid):
    mensaje = request.form['mensaje']
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("INSERT INTO comunicaciones (caso_id, remitente, mensaje) VALUES (%s,%s,%s)",
                  (cid, session['nombre'], mensaje))
        conexion.commit()
    conexion.close()
    return redirect(url_for('detalle_caso', cid=cid))


@app.route('/caso/<int:cid>/cerrar', methods=['POST'])
@admin_required
def cerrar_caso(cid):
    calif = request.form['calificacion']
    lecciones = request.form['lecciones']
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("INSERT INTO cierres_retroalimentacion (caso_id, calificacion_satisfaccion, lecciones_aprendidas) VALUES (%s,%s,%s)",
                  (cid, calif, lecciones))
        c.execute("UPDATE casos SET estatus_caso='Cerrado' WHERE id=%s", (cid,))
        conexion.commit()
    conexion.close()
    return redirect(url_for('detalle_caso', cid=cid))


@app.route('/instituciones', methods=['GET', 'POST'])
@admin_required
def instituciones():
    conexion = obtener_conexion()
    if request.method == 'POST':
        with conexion.cursor() as c:
            c.execute("INSERT INTO instituciones (nombre_institucion, especialidad, contacto) VALUES (%s,%s,%s)",
                      (request.form['nombre'], request.form['especialidad'], request.form['contacto']))
            conexion.commit()
        conexion.close()
        return redirect(url_for('instituciones'))
    with conexion.cursor() as c:
        c.execute("SELECT * FROM instituciones ORDER BY id DESC")
        instituciones = c.fetchall()
    conexion.close()
    return render_template('instituciones.html', instituciones=instituciones)


@app.route('/institucion/<int:iid>')
@admin_required
def detalle_institucion(iid):
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("SELECT * FROM instituciones WHERE id=%s", (iid,))
        institucion = c.fetchone()
        if not institucion:
            conexion.close()
            return redirect(url_for('instituciones'))
        c.execute("SELECT * FROM canalizaciones WHERE institucion_id=%s ORDER BY id DESC", (iid,))
        canalizaciones = c.fetchall()
        c.execute("""SELECT COUNT(*) AS t FROM casos ca
                     JOIN canalizaciones cn ON cn.reporte_id = ca.reporte_id
                     WHERE cn.institucion_id=%s AND ca.estatus_caso='Cerrado'""", (iid,))
        cerrados = c.fetchone()['t']
    conexion.close()
    return render_template('detalle_institucion.html',
                           institucion=institucion,
                           canalizaciones=canalizaciones,
                           cerrados=cerrados)


@app.route('/canalizaciones', methods=['GET', 'POST'])
@admin_required
def canalizaciones():
    conexion = obtener_conexion()
    if request.method == 'POST':
        with conexion.cursor() as c:
            c.execute("INSERT INTO canalizaciones (reporte_id, institucion_id) VALUES (%s,%s)",
                      (request.form['reporte_id'], request.form['institucion_id']))
            conexion.commit()
        conexion.close()
        return redirect(url_for('canalizaciones'))
    with conexion.cursor() as c:
        c.execute("""SELECT ca.*, i.nombre_institucion FROM canalizaciones ca
                     JOIN instituciones i ON i.id=ca.institucion_id
                     ORDER BY ca.id DESC""")
        canalizaciones = c.fetchall()
        c.execute("SELECT * FROM instituciones")
        instituciones = c.fetchall()
    conexion.close()
    return render_template('canalizaciones.html',
                           canalizaciones=canalizaciones, instituciones=instituciones)


@app.route('/evaluaciones')
@admin_required
def evaluaciones():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("SELECT * FROM evaluaciones ORDER BY prioridad DESC")
        evaluaciones = c.fetchall()
    conexion.close()
    return render_template('evaluaciones.html', evaluaciones=evaluaciones)


@app.route('/evaluaciones/nueva', methods=['GET', 'POST'])
@admin_required
def nueva_evaluacion():
    conexion = obtener_conexion()
    if request.method == 'POST':
        with conexion.cursor() as c:
            c.execute(
                "INSERT INTO evaluaciones (reporte_id, nivel_riesgo, prioridad) VALUES (%s,%s,%s)",
                (request.form['reporte_id'], request.form['nivel_riesgo'],
                 request.form['prioridad'])
            )
            conexion.commit()
        conexion.close()
        return redirect(url_for('evaluaciones'))

    with conexion.cursor() as c:
        c.execute("SELECT * FROM reportes ORDER BY id DESC")
        reportes = c.fetchall()
    conexion.close()
    return render_template('nueva_evaluacion.html', reportes=reportes)


@app.route('/cierres')
@admin_required
def cierres():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("""SELECT cr.*, ca.reporte_id, ca.responsable
                     FROM cierres_retroalimentacion cr
                     JOIN casos ca ON ca.id = cr.caso_id
                     ORDER BY cr.id DESC""")
        cierres = c.fetchall()
    conexion.close()
    if cierres:
        promedio = round(sum(c['calificacion_satisfaccion'] for c in cierres) / len(cierres), 1)
        cinco = sum(1 for c in cierres if c['calificacion_satisfaccion'] == 5)
    else:
        promedio = 0
        cinco = 0
    return render_template('cierres.html', cierres=cierres,
                           promedio=promedio, cinco_estrellas=cinco)


@app.route('/mensajes')
@admin_required
def mensajes():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("""SELECT ca.id AS caso_id, ca.reporte_id, ca.responsable
                     FROM casos ca
                     WHERE ca.id IN (SELECT DISTINCT caso_id FROM comunicaciones)
                     ORDER BY ca.id DESC""")
        casos_con_msg = c.fetchall()
        conversaciones = []
        for caso in casos_con_msg:
            c.execute("SELECT * FROM comunicaciones WHERE caso_id=%s ORDER BY id",
                      (caso['caso_id'],))
            msgs = c.fetchall()
            conversaciones.append({**caso, 'mensajes': msgs})
    conexion.close()
    return render_template('mensajes.html', conversaciones=conversaciones)


@app.route('/evidencias', methods=['GET', 'POST'])
@admin_required
def evidencias():
    conexion = obtener_conexion()
    if request.method == 'POST':
        archivo = request.files.get('archivo')
        ruta = ''
        if archivo and archivo.filename:
            nombre = secure_filename(archivo.filename)
            archivo.save(os.path.join(UPLOAD_DIR, nombre))
            ruta = f"/static/uploads/{nombre}"
        with conexion.cursor() as c:
            c.execute(
                "INSERT INTO documentos_evidencia (caso_id, ruta_archivo, tipo_evidencia) VALUES (%s,%s,%s)",
                (request.form['caso_id'], ruta, request.form['tipo_evidencia'])
            )
            conexion.commit()
        conexion.close()
        return redirect(url_for('evidencias'))

    with conexion.cursor() as c:
        c.execute("SELECT * FROM documentos_evidencia ORDER BY id DESC")
        evidencias = c.fetchall()
        c.execute("SELECT id, reporte_id FROM casos ORDER BY id DESC")
        casos = c.fetchall()
        c.execute("SELECT COUNT(DISTINCT caso_id) AS t FROM documentos_evidencia")
        casos_con_evidencia = c.fetchone()['t']
    conexion.close()
    return render_template('evidencias.html', evidencias=evidencias,
                           casos=casos, casos_con_evidencia=casos_con_evidencia)


@app.route('/seguimientos')
@admin_required
def seguimientos():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("""SELECT st.*, ca.responsable
                     FROM seguimiento_tiempo st
                     JOIN casos ca ON ca.id = st.caso_id
                     ORDER BY st.id DESC""")
        seguimientos = c.fetchall()
    conexion.close()
    return render_template('seguimientos.html', seguimientos=seguimientos)


@app.route('/usuarios')
@admin_required
def admin_usuarios():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("SELECT id, nombre, correo FROM usuarios ORDER BY id DESC")
        usuarios = c.fetchall()
    conexion.close()
    return render_template('admin_usuarios.html', usuarios=usuarios)


@app.route('/usuarios/<int:uid>/eliminar')
@admin_required
def eliminar_usuario(uid):
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("DELETE FROM usuarios WHERE id=%s", (uid,))
        conexion.commit()
    conexion.close()
    return redirect(url_for('admin_usuarios'))


# ---------- PERFIL Y ESTADÍSTICAS ----------
@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    conexion = obtener_conexion()
    if request.method == 'POST':
        nombre = request.form['nombre']
        correo = request.form['correo']
        password = request.form.get('password')
        with conexion.cursor() as c:
            if password:
                c.execute("UPDATE usuarios SET nombre=%s, correo=%s, password=%s WHERE id=%s",
                          (nombre, correo, password, session['usuario_id']))
            else:
                c.execute("UPDATE usuarios SET nombre=%s, correo=%s WHERE id=%s",
                          (nombre, correo, session['usuario_id']))
            conexion.commit()
        session['nombre'] = nombre
        conexion.close()
        return redirect(url_for('perfil'))

    with conexion.cursor() as c:
        c.execute("SELECT * FROM usuarios WHERE id=%s", (session['usuario_id'],))
        usuario = c.fetchone()
        c.execute("SELECT COUNT(*) AS t FROM reportes"); total = c.fetchone()['t']
        c.execute("SELECT COUNT(*) AS t FROM casos WHERE estatus_caso='Cerrado'"); cerr = c.fetchone()['t']
    conexion.close()
    return render_template('perfil.html', usuario=usuario,
                           total_reportes=total, resueltos=cerr)


@app.route('/estadisticas')
def estadisticas():
    conexion = obtener_conexion()
    with conexion.cursor() as c:
        c.execute("SELECT COUNT(*) AS t FROM reportes"); total_reportes = c.fetchone()['t']
        c.execute("SELECT COUNT(*) AS t FROM usuarios"); total_usuarios = c.fetchone()['t']
        c.execute("SELECT COUNT(*) AS t FROM instituciones"); total_inst = c.fetchone()['t']
        c.execute("SELECT COUNT(*) AS t FROM casos WHERE estatus_caso='Cerrado'"); cerrados = c.fetchone()['t']
        c.execute("SELECT nivel_riesgo, COUNT(*) AS total FROM evaluaciones GROUP BY nivel_riesgo")
        datos_riesgo = c.fetchall()
        c.execute("SELECT estatus_caso, COUNT(*) AS total FROM casos GROUP BY estatus_caso")
        datos_estados = c.fetchall()
    conexion.close()
    total_casos = sum(d['total'] for d in datos_estados) or 1
    return render_template('estadisticas.html',
                           total_reportes=total_reportes, total_usuarios=total_usuarios,
                           total_instituciones=total_inst, cerrados=cerrados,
                           datos_riesgo=datos_riesgo, datos_estados=datos_estados,
                           total_casos=total_casos)


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


if __name__ == '__main__':
    app.run(debug=True, port=5000)