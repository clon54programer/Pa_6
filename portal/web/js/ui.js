"use strict";

const UI = (() => {
  const ESTADOS = {
    EN_TRANSITO: "En tránsito",
    EN_MUELLE: "En muelle",
    ALMACENADO: "Almacenado en bodega",
    EN_DESPACHO: "En proceso de despacho",
    DESPACHADO: "Despachado",
  };

  const formatoFecha = new Intl.DateTimeFormat("es-CO", {
    dateStyle: "medium",
    timeStyle: "short",
  });

  function crear(etiqueta, clase, texto) {
    const elemento = document.createElement(etiqueta);
    if (clase) {
      elemento.className = clase;
    }
    if (texto !== undefined && texto !== null) {
      elemento.textContent = texto;
    }
    return elemento;
  }

  function formatearFecha(valor) {
    if (!valor) {
      return "—";
    }
    const soloFecha = /^\d{4}-\d{2}-\d{2}$/.test(valor);
    const fecha = new Date(soloFecha ? valor + "T00:00:00" : valor);
    if (Number.isNaN(fecha.getTime())) {
      return valor;
    }
    return formatoFecha.format(fecha);
  }

  function claseEstado(estado) {
    return "pill pill--" + String(estado || "").toLowerCase().replaceAll("_", "-");
  }

  function renderAvisos(avisos, lista) {
    lista.replaceChildren();
    if (!avisos || avisos.length === 0) {
      const vacio = crear("li", "aviso aviso-vacio", "No hay avisos vigentes.");
      lista.append(vacio);
      return;
    }
    for (const aviso of avisos) {
      const elemento = crear("li", "aviso aviso--" + aviso.severidad);
      elemento.append(crear("h3", null, aviso.titulo));
      elemento.append(crear("p", null, aviso.detalle));
      elemento.append(
        crear(
          "small",
          null,
          "Vigencia: " + formatearFecha(aviso.desde) + " — " + formatearFecha(aviso.hasta)
        )
      );
      lista.append(elemento);
    }
  }

  function renderResultado(datos, contenedor) {
    contenedor.replaceChildren();
    const contenedorDatos = datos.contenedor;
    const articulo = crear("article", "resultado-articulo");

    const cabecera = crear("div", "resultado-cabecera");
    cabecera.append(crear("h2", null, "Contenedor " + contenedorDatos.numero));
    cabecera.append(
      crear("span", claseEstado(contenedorDatos.estado), ESTADOS[contenedorDatos.estado] || contenedorDatos.estado)
    );
    articulo.append(cabecera);

    const detalles = crear("dl", "detalles");
    const campos = [
      ["BL", contenedorDatos.bl],
      ["Orden de despacho", contenedorDatos.orden],
      ["Importador / exportador", contenedorDatos.importador],
      ["Buque", contenedorDatos.buque],
      ["Arribo", formatearFecha(contenedorDatos.arribo)],
      ["Muelle", contenedorDatos.muelle],
      ["Bodega", contenedorDatos.bodega],
      ["Actualizado", formatearFecha(contenedorDatos.actualizado)],
    ];
    for (const [rotulo, valor] of campos) {
      const bloque = crear("div", "detalle");
      bloque.append(crear("dt", null, rotulo));
      bloque.append(crear("dd", null, valor));
      detalles.append(bloque);
    }
    articulo.append(detalles);

    articulo.append(crear("h3", null, "Trazabilidad"));
    const linea = crear("ol", "timeline");
    for (const hito of datos.hitos || []) {
      const elemento = crear("li", "hito" + (hito.completado ? " completado" : ""));
      elemento.append(crear("p", "hito-titulo", hito.titulo));
      const momento = hito.completado ? formatearFecha(hito.ts) : "Pendiente";
      elemento.append(crear("p", "hito-meta", momento + " · " + hito.ubicacion));
      elemento.append(crear("p", "hito-detalle", hito.detalle));
      linea.append(elemento);
    }
    articulo.append(linea);
    contenedor.append(articulo);
  }

  function mostrarError(elemento, mensaje) {
    elemento.textContent = mensaje;
    elemento.hidden = false;
  }

  function ocultarError(elemento) {
    elemento.textContent = "";
    elemento.hidden = true;
  }

  function ocupado(boton, activo, textoOriginal) {
    boton.disabled = activo;
    if (activo) {
      boton.textContent = "Procesando…";
    } else if (textoOriginal) {
      boton.textContent = textoOriginal;
    }
  }

  return {
    ESTADOS,
    crear,
    formatearFecha,
    renderAvisos,
    renderResultado,
    mostrarError,
    ocultarError,
    ocupado,
  };
})();
