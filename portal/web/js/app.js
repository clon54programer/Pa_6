"use strict";

(() => {
  const porId = (id) => document.getElementById(id);

  const elementos = {
    tls: porId("tls-badge"),
    indicador: porId("indicador"),
    indicadorPunto: porId("indicador-punto"),
    indicadorTexto: porId("indicador-texto"),
    tarjetaLogin: porId("tarjeta-login"),
    tarjetaSesion: porId("tarjeta-sesion"),
    nombreSesion: porId("nombre-sesion"),
    formLogin: porId("form-login"),
    usuario: porId("usuario"),
    password: porId("password"),
    btnLogin: porId("btn-login"),
    errorLogin: porId("error-login"),
    btnSalir: porId("btn-salir"),
    btnCerrarSesion: porId("btn-cerrar-sesion"),
    seccionSeguimiento: porId("seccion-seguimiento"),
    formBusqueda: porId("form-busqueda"),
    consulta: porId("consulta"),
    btnConsultar: porId("btn-consultar"),
    errorBusqueda: porId("error-busqueda"),
    resultado: porId("resultado"),
    listaAvisos: porId("lista-avisos"),
  };

  const estado = {
    autenticado: false,
    csrf: null,
    navegadorMs: null,
    ultimoServidor: null,
    intervalo: null,
    cuenta: null,
  };

  function marcarPunto(clase) {
    elementos.indicadorPunto.classList.remove("ok", "alerta", "error");
    if (clase) {
      elementos.indicadorPunto.classList.add(clase);
    }
  }

  function pintarIndicador(datos) {
    if (!datos) {
      return;
    }
    estado.ultimoServidor = datos;
    const segundos = (datos.latencia_ms / 1000).toFixed(2);
    let texto = `${segundos} s · ${datos.fuente}`;
    if (estado.navegadorMs !== null) {
      texto += ` · navegador ${(estado.navegadorMs / 1000).toFixed(2)} s`;
    }
    elementos.indicadorTexto.textContent = texto;
    elementos.indicador.title =
      "Última medición: " +
      datos.timestamp +
      " · umbral " +
      (datos.umbral_ms / 1000).toFixed(1) +
      " s";
    if (datos.fuente === "simulado") {
      marcarPunto("alerta");
    } else if (datos.estado === "DEGRADED") {
      marcarPunto("error");
    } else {
      marcarPunto("ok");
    }
  }

  async function actualizarEstado() {
    if (!estado.autenticado) {
      return;
    }
    const inicio = performance.now();
    try {
      const datos = await API.estado();
      estado.navegadorMs = performance.now() - inicio;
      pintarIndicador(datos);
    } catch (error) {
      if (error.status === 401) {
        reiniciarSesion();
        return;
      }
      elementos.indicadorTexto.textContent = "Sin datos de rendimiento";
      marcarPunto("error");
    }
  }

  async function cargarAvisos() {
    try {
      const datos = await API.avisos();
      UI.renderAvisos(datos.avisos, elementos.listaAvisos);
    } catch (error) {
      if (error.status === 401) {
        reiniciarSesion();
        return;
      }
      elementos.listaAvisos.replaceChildren(
        UI.crear("li", "aviso aviso-vacio", "No se pudieron cargar los avisos.")
      );
    }
  }

  function detenerCuenta() {
    if (estado.cuenta !== null) {
      clearInterval(estado.cuenta);
      estado.cuenta = null;
    }
  }

  function iniciarCuenta(segundos) {
    detenerCuenta();
    let restante = Math.max(1, Math.ceil(segundos));
    const actualizar = () => {
      if (restante <= 0) {
        detenerCuenta();
        elementos.btnLogin.disabled = false;
        elementos.btnLogin.textContent = "Ingresar";
        UI.ocultarError(elementos.errorLogin);
        return;
      }
      UI.mostrarError(
        elementos.errorLogin,
        `Demasiados intentos fallidos. Espera ${restante} segundo${restante === 1 ? "" : "s"}.`
      );
      elementos.btnLogin.disabled = true;
      elementos.btnLogin.textContent = "Bloqueado";
      restante -= 1;
    };
    actualizar();
    estado.cuenta = setInterval(actualizar, 1000);
  }

  function entrarSesion(datos) {
    estado.autenticado = true;
    estado.csrf = datos.csrf;
    elementos.tarjetaLogin.hidden = true;
    elementos.tarjetaSesion.hidden = false;
    elementos.nombreSesion.textContent = datos.nombre || datos.usuario || "cliente";
    elementos.btnSalir.hidden = false;
    elementos.seccionSeguimiento.hidden = false;
    UI.ocultarError(elementos.errorLogin);
    UI.ocultarError(elementos.errorBusqueda);
    elementos.consulta.focus();
    cargarAvisos();
    actualizarEstado();
    if (estado.intervalo === null) {
      estado.intervalo = setInterval(actualizarEstado, 30000);
    }
  }

  function reiniciarSesion() {
    estado.autenticado = false;
    estado.csrf = null;
    estado.navegadorMs = null;
    estado.ultimoServidor = null;
    if (estado.intervalo !== null) {
      clearInterval(estado.intervalo);
      estado.intervalo = null;
    }
    detenerCuenta();
    elementos.tarjetaLogin.hidden = false;
    elementos.tarjetaSesion.hidden = true;
    elementos.btnSalir.hidden = true;
    elementos.seccionSeguimiento.hidden = true;
    elementos.btnLogin.disabled = false;
    elementos.btnLogin.textContent = "Ingresar";
    elementos.resultado.replaceChildren();
    elementos.errorBusqueda.hidden = true;
    elementos.listaAvisos.replaceChildren(
      UI.crear("li", "aviso aviso-vacio", "Inicia sesión para ver los avisos vigentes.")
    );
    elementos.indicadorTexto.textContent = "Sesión requerida";
    elementos.indicador.removeAttribute("title");
    marcarPunto(null);
  }

  async function salir() {
    const csrf = estado.csrf;
    reiniciarSesion();
    if (csrf) {
      try {
        await API.logout(csrf);
      } catch (error) {
        /* La sesión local ya se cerró; el servidor la descarta por TTL. */
      }
    }
  }

  async function entrar(evento) {
    evento.preventDefault();
    if (estado.cuenta !== null) {
      return;
    }
    UI.ocultarError(elementos.errorLogin);
    const usuario = elementos.usuario.value.trim();
    const password = elementos.password.value;
    if (!usuario || !password) {
      UI.mostrarError(elementos.errorLogin, "Escribe tu usuario y contraseña.");
      return;
    }

    const inicio = performance.now();
    UI.ocupado(elementos.btnLogin, true, "Ingresar");
    try {
      const datos = await API.login(usuario, password);
      estado.navegadorMs = performance.now() - inicio;
      elementos.password.value = "";
      entrarSesion(datos);
    } catch (error) {
      if (error.status === 429) {
        const segundos = (error.datos && error.datos.retry_after_s) || 120;
        iniciarCuenta(segundos);
      } else {
        UI.mostrarError(elementos.errorLogin, error.message);
        elementos.password.select();
      }
    } finally {
      if (estado.cuenta === null) {
        UI.ocupado(elementos.btnLogin, false, "Ingresar");
      }
    }
  }

  async function buscar(evento) {
    evento.preventDefault();
    if (!estado.autenticado) {
      return;
    }
    const consulta = elementos.consulta.value.trim();
    if (!consulta) {
      UI.mostrarError(elementos.errorBusqueda, "Escribe un número, BL u orden.");
      return;
    }

    UI.ocultarError(elementos.errorBusqueda);
    UI.ocupado(elementos.btnConsultar, true, "Consultar");
    const inicio = performance.now();
    try {
      const datos = await API.track(consulta);
      estado.navegadorMs = performance.now() - inicio;
      UI.renderResultado(datos, elementos.resultado);
      if (estado.ultimoServidor) {
        pintarIndicador(estado.ultimoServidor);
      }
    } catch (error) {
      elementos.resultado.replaceChildren();
      if (error.status === 401) {
        reiniciarSesion();
        return;
      }
      UI.mostrarError(elementos.errorBusqueda, error.message);
    } finally {
      UI.ocupado(elementos.btnConsultar, false, "Consultar");
    }
  }

  function iniciar() {
    if (location.protocol === "https:") {
      elementos.tls.hidden = false;
    }
    elementos.formLogin.addEventListener("submit", entrar);
    elementos.formBusqueda.addEventListener("submit", buscar);
    elementos.btnSalir.addEventListener("click", salir);
    elementos.btnCerrarSesion.addEventListener("click", salir);

    for (const boton of document.querySelectorAll("[data-ejemplo]")) {
      boton.addEventListener("click", () => {
        elementos.consulta.value = boton.dataset.ejemplo;
        elementos.consulta.focus();
        elementos.formBusqueda.requestSubmit();
      });
    }

    API.sesion()
      .then((datos) => {
        if (datos && datos.autenticado) {
          entrarSesion(datos);
        } else {
          reiniciarSesion();
        }
      })
      .catch(() => {
        reiniciarSesion();
        UI.mostrarError(elementos.errorLogin, "No se pudo conectar con el servidor.");
      });
  }

  iniciar();
})();
