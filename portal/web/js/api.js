"use strict";

const API = (() => {
  async function pedir(ruta, opciones = {}) {
    const control = new AbortController();
    const temporizador = setTimeout(() => control.abort(), 10000);
    try {
      const respuesta = await fetch(ruta, {
        credentials: "same-origin",
        signal: control.signal,
        ...opciones,
      });
      let datos = null;
      if (respuesta.status !== 204) {
        const texto = await respuesta.text();
        if (texto) {
          try {
            datos = JSON.parse(texto);
          } catch (error) {
            datos = null;
          }
        }
      }
      if (!respuesta.ok) {
        const mensaje =
          (datos && datos.error && datos.error.mensaje) ||
          "No se pudo completar la solicitud.";
        const fallo = new Error(mensaje);
        fallo.status = respuesta.status;
        fallo.datos = datos;
        throw fallo;
      }
      return datos;
    } finally {
      clearTimeout(temporizador);
    }
  }

  return {
    pedir,
    sesion: () => pedir("/api/sesion"),
    login: (usuario, password) =>
      pedir("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usuario, password }),
      }),
    logout: (csrf) =>
      pedir("/api/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf },
      }),
    track: (consulta) => pedir("/api/track?q=" + encodeURIComponent(consulta)),
    avisos: () => pedir("/api/avisos"),
    estado: () => pedir("/api/estado"),
  };
})();
