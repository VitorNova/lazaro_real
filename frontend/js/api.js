/* === api.js === */
/* API URL global - definida uma unica vez */
var API_URL = window.location.hostname === 'localhost'
    ? 'http://localhost:3115'
    : window.location.origin;
