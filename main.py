from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from pydantic import BaseModel
from typing import Optional
import hashlib # <-- NUEVO: Para encriptar contraseñas

app = FastAPI(title="Backend Polla Mundialista 2026")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tu enlace real a Supabase
DB_URI = "postgresql://postgres.rqdpvskodddutvbbxkrh:YRUNM4DIuUCN9oTu@aws-1-us-east-1.pooler.supabase.com:6543/postgres"

def obtener_conexion():
    try:
        conn = psycopg2.connect(DB_URI)
        return conn
    except Exception as e:
        print(f"Error al conectar a la DB: {e}")
        return None

# --- FUNCIÓN DE SEGURIDAD PARA CONTRASEÑAS ---
def encriptar_clave(clave_plana: str) -> str:
    """Convierte '1234' en un código indescifrable de 64 caracteres"""
    return hashlib.sha256(clave_plana.encode()).hexdigest()

# --- MOLDES DE DATOS ---
class EsquemaUsuario(BaseModel):
    username: str
    clave: str

class EsquemaPrediccion(BaseModel):
    username: str
    partido_id: str
    goles_a_pred: int
    goles_b_pred: int
    penales_a_pred: Optional[int] = None
    penales_b_pred: Optional[int] = None

class EsquemaResultadoReal(BaseModel):
    partido_id: str
    goles_a_real: int
    goles_b_real: int

class EsquemaSincronizarLlaves(BaseModel):
    llaves: dict # Recibirá algo como {"49": {"eqA": "México", "eqB": "Argentina"}}


# --- ENDPOINTS / RUTAS ---

@app.get("/")
def inicio():
    return {"mensaje": "¡Servidor de la Polla 2026 corriendo en la nube! 🚀"}

@app.post("/registro")
def registrar_usuario(datos: EsquemaUsuario):
    conexion = obtener_conexion()
    if not conexion:
        raise HTTPException(status_code=500, detail="Error de DB")
    try:
        cursor = conexion.cursor()
        user_limpio = datos.username.strip().lower()
        
        cursor.execute("SELECT id FROM usuarios WHERE username = %s;", (user_limpio,))
        if cursor.fetchone():
            cursor.close()
            conexion.close()
            raise HTTPException(status_code=400, detail="El usuario ya existe")
            
        # 🔥 Encriptamos la clave antes de guardarla
        clave_segura = encriptar_clave(datos.clave.strip())
        
        cursor.execute("INSERT INTO usuarios (username, clave) VALUES (%s, %s);", (user_limpio, clave_segura))
        conexion.commit()
        cursor.close()
        conexion.close()
        return {"exito": True, "mensaje": f"Usuario {user_limpio} registrado"}
    except HTTPException as he:
        raise he
    except Exception as e:
        conexion.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login")
def login_usuario(datos: EsquemaUsuario):
    conexion = obtener_conexion()
    if not conexion:
        raise HTTPException(status_code=500, detail="Error de DB")
    try:
        cursor = conexion.cursor()
        user_limpio = datos.username.strip().lower()
        cursor.execute("SELECT username, clave, is_admin FROM usuarios WHERE username = %s;", (user_limpio,))
        usuario = cursor.fetchone()
        cursor.close()
        conexion.close()
        
        if not usuario:
            raise HTTPException(status_code=401, detail="El usuario no existe")
            
        db_username, db_clave_encriptada, is_admin = usuario
        clave_intento_encriptada = encriptar_clave(datos.clave.strip())
        
        # 🔥 Comparamos los hashes, no los textos planos
        if db_clave_encriptada != clave_intento_encriptada:
            raise HTTPException(status_code=401, detail="Contraseña incorrecta")
            
        return {"exito": True, "username": db_username, "isAdmin": is_admin}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/predicciones/guardar")
def guardar_prediccion(datos: EsquemaPrediccion):
    conexion = obtener_conexion()
    if not conexion:
        raise HTTPException(status_code=500, detail="Error de DB")
    try:
        cursor = conexion.cursor()
        user_limpio = datos.username.strip().lower()
        
        cursor.execute("SELECT id FROM usuarios WHERE username = %s;", (user_limpio,))
        res_user = cursor.fetchone()
        if not res_user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        usuario_id = res_user[0]
        
        id_pred_unica = f"{user_limpio}_{datos.partido_id}"
        
        cursor.execute(
            """INSERT INTO predicciones (id_prediccion, usuario_id, partido_id, goles_a_pred, goles_b_pred, penales_a_pred, penales_b_pred)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id_prediccion) 
               DO UPDATE SET 
                  goles_a_pred = EXCLUDED.goles_a_pred,
                  goles_b_pred = EXCLUDED.goles_b_pred,
                  penales_a_pred = EXCLUDED.penales_a_pred,
                  penales_b_pred = EXCLUDED.penales_b_pred,
                  updated_at = NOW();""",
            (id_pred_unica, usuario_id, datos.partido_id, datos.goles_a_pred, datos.goles_b_pred, datos.penales_a_pred, datos.penales_b_pred)
        )
        conexion.commit()
        cursor.close()
        conexion.close()
        return {"exito": True, "mensaje": "Predicción guardada exitosamente"}
    except HTTPException as he:
        raise he
    except Exception as e:
        conexion.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboard/{username}")
def obtener_dashboard(username: str):
    conexion = obtener_conexion()
    if not conexion:
        raise HTTPException(status_code=500, detail="Error de DB")
    try:
        cursor = conexion.cursor()
        user_limpio = username.strip().lower()
        
        # Le agregamos equipo_a_real y b_real a la consulta
        consulta_partidos = """
            SELECT p.id, p.fecha, p.hora, p.fase, p.equipo_a, p.equipo_b, 
                   p.goles_a_real, p.goles_b_real, p.estado,
                   p.equipo_a_real, p.equipo_b_real, p.penales_a_real, p.penales_b_real,
                   pr.goles_a_pred, pr.goles_b_pred, pr.puntos_calculados, pr.penales_a_pred, pr.penales_b_pred
            FROM partidos p
            LEFT JOIN predicciones pr ON p.id = pr.partido_id 
                AND pr.usuario_id = (SELECT id FROM usuarios WHERE username = %s)
            ORDER BY NULLIF(regexp_replace(p.id, '\D', '', 'g'), '')::int ASC;
        """
        cursor.execute(consulta_partidos, (user_limpio,))
        filas_partidos = cursor.fetchall()
        lista_partidos = []
        for f in filas_partidos:
            lista_partidos.append({
                "id": f[0], "fecha": f[1], "hora": f[2], "fase": f[3], "equipo_a": f[4], "equipo_b": f[5],
                "goles_a_real": f[6], "goles_b_real": f[7], "estado": f[8],
                "equipo_a_real": f[9], "equipo_b_real": f[10], "penales_a_real": f[11], "penales_b_real": f[12],
                "prediccion": {"goles_a_pred": f[13], "goles_b_pred": f[14], "puntos_ganados": f[15], "penales_a_pred": f[16], "penales_b_pred": f[17]} if f[13] is not None else None
            })
            
        cursor.execute("""
            SELECT username, puntos_total, exactos, tendencia 
            FROM usuarios 
            WHERE is_admin = FALSE
            ORDER BY puntos_total DESC, exactos DESC, username ASC;
        """)
        filas_ranking = cursor.fetchall()
        lista_ranking = []
        for r in filas_ranking:
            lista_ranking.append({"username": r[0], "puntos_total": r[1], "exactos": r[2], "tendencia": r[3]})
        cursor.close()
        conexion.close()
        return {"exito": True, "partidos": lista_partidos, "ranking": lista_ranking}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/actualizar-resultado")
def actualizar_resultado(datos: EsquemaResultadoReal):
    conexion = obtener_conexion()
    if not conexion:
        raise HTTPException(status_code=500, detail="Error de DB")
    try:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE partidos SET goles_a_real = %s, goles_b_real = %s, estado = 'Finalizado' WHERE id = %s;",
            (datos.goles_a_real, datos.goles_b_real, datos.partido_id)
        )
        cursor.execute("SELECT id, goles_a_pred, goles_b_pred FROM predicciones WHERE partido_id = %s;", (datos.partido_id,))
        predicciones_usuarios = cursor.fetchall()
        
        real_a, real_b = datos.goles_a_real, datos.goles_b_real
        
        for pred in predicciones_usuarios:
            pred_id, pred_a, pred_b = pred
            puntos = 0
            if pred_a == real_a and pred_b == real_b: puntos = 5
            elif (pred_a > pred_b and real_a > real_b) or (pred_a < pred_b and real_a < real_b) or (pred_a == pred_b and real_a == real_b): puntos = 3
            cursor.execute("UPDATE predicciones SET puntos_calculados = %s WHERE id = %s;", (puntos, pred_id))
            
        cursor.execute("""
            UPDATE usuarios u
            SET puntos_total = COALESCE((SELECT SUM(puntos_calculados) FROM predicciones WHERE usuario_id = u.id), 0),
                exactos = COALESCE((SELECT COUNT(*) FROM predicciones WHERE usuario_id = u.id AND puntos_calculados = 5), 0),
                tendencia = COALESCE((SELECT COUNT(*) FROM predicciones WHERE usuario_id = u.id AND puntos_calculados = 3), 0);
        """)
        conexion.commit()
        cursor.close()
        conexion.close()
        return {"exito": True, "mensaje": "Puntos recalculados"}
    except Exception as e:
        conexion.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# 🔥 NUEVO ENDPOINT: BOTÓN DORADO (SINCRONIZAR LLAVES)
@app.post("/admin/sincronizar-llaves")
def sincronizar_llaves(datos: EsquemaSincronizarLlaves):
    conexion = obtener_conexion()
    if not conexion:
        raise HTTPException(status_code=500, detail="Error de DB")
    try:
        cursor = conexion.cursor()
        # Iteramos sobre el diccionario que mandó el Frontend
        for partido_id, equipos in datos.llaves.items():
            cursor.execute(
                "UPDATE partidos SET equipo_a_real = %s, equipo_b_real = %s WHERE id = %s;",
                (equipos.get("eqA", ""), equipos.get("eqB", ""), str(partido_id))
            )
        conexion.commit()
        cursor.close()
        conexion.close()
        return {"exito": True, "mensaje": "¡Equipos clasificados guardados oficialmente!"}
    except Exception as e:
        conexion.rollback()
        raise HTTPException(status_code=500, detail=f"Error sincronizando llaves: {str(e)}")