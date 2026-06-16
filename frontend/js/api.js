/**
 * SSLAB API 封装层
 * 统一 AJAX 调用、错误处理、超时、重试
 * 依赖：jQuery（已在页面加载）
 */

(function(global) {
    'use strict';

    // 由 index.html 注入的全局变量
    function getBase() {
        var h = global.host || '127.0.0.1';
        var p = global.httpPort || 1880;
        return 'http://' + h + ':' + p;
    }

    /**
     * 通用请求包装
     * @param {string} method
     * @param {string} path
     * @param {object|null} body
     * @param {object} opts  { timeout, retries }
     * @returns {Promise<{ok:boolean, data:any, status:number, error:string}>}
     */
    function request(method, path, body, opts) {
        opts = opts || {};
        var timeout = opts.timeout || 8000;
        var retriesLeft = (opts.retries != null ? opts.retries : 1);

        function attempt() {
            return new Promise(function(resolve) {
                var ajaxOpts = {
                    type: method,
                    url: getBase() + path,
                    timeout: timeout,
                    success: function(data, status, xhr) {
                        resolve({ ok: true, data: data, status: xhr.status, error: '' });
                    },
                    error: function(xhr, textStatus, errorThrown) {
                        var msg = textStatus || errorThrown || 'network error';
                        if (retriesLeft > 0) {
                            retriesLeft--;
                            setTimeout(function() {
                                attempt().then(resolve);
                            }, 400);
                        } else {
                            resolve({ ok: false, data: null, status: xhr.status || 0, error: msg });
                        }
                    }
                };
                if (body != null) {
                    ajaxOpts.contentType = 'application/json';
                    ajaxOpts.data = JSON.stringify(body);
                }
                $.ajax(ajaxOpts);
            });
        }

        return attempt();
    }

    var API = {
        /** GET /req — 当前系统状态 */
        getState: function() {
            return request('GET', '/req', null, { timeout: 5000 });
        },

        /** GET /api/devices — 设备列表 */
        getDevices: function() {
            return request('GET', '/api/devices', null, { timeout: 5000 });
        },

        /** GET /api/scan — 触发扫描 */
        scan: function(ports, clear) {
            var q = '';
            if (ports) q += '?ports=' + encodeURIComponent(ports);
            if (clear) q += (q ? '&' : '?') + 'clear=true';
            return request('GET', '/api/scan' + q, null, { timeout: 60000 });
        },

        /** GET /api/rs485/log — RS485 事务日志 */
        getRS485Log: function(limit) {
            return request('GET', '/api/rs485/log?limit=' + (limit || 50), null, { timeout: 5000 });
        },

        /**
         * POST /{domain}/{deviceId} — 控制命令
         * @param {string} domain
         * @param {string} deviceId
         * @param {any} value
         */
        control: function(domain, deviceId, value) {
            var isBool = (typeof value === 'boolean');
            var num = isBool ? (value ? 1 : 0) : (isFinite(value) ? Number(value) : undefined);
            var body = {};
            body[deviceId] = value;
            body.value = (num !== undefined ? num : value);
            body.state = (num !== undefined ? num : (isBool ? (value ? 1 : 0) : undefined));
            body.bool = !!(isBool ? value : (num !== undefined ? (num !== 0) : !!value));
            body.text = isBool ? (value ? 'on' : 'off') : String(value);
            return request('POST', '/' + domain + '/' + deviceId, body, { timeout: 8000, retries: 1 });
        },

        /** GET /api/rs485/ports — 列出本机所有可用 COM 口 */
        rs485Ports: function() {
            return request('GET', '/api/rs485/ports', null, { timeout: 8000 });
        },

        /** POST /api/rs485/autodetect — 自动检测 RS485 COM 口并写入配置
         *  @param {string[]} exclude  排除的端口列表，如 ['COM5','COM16']
         */
        rs485Autodetect: function(exclude) {
            var body = { exclude: exclude || [] };
            return request('POST', '/api/rs485/autodetect', body, { timeout: 15000 });
        }
    };

    global.SSLABAPI = API;

})(window);
