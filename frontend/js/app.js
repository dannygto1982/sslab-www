/**
 * SSLAB App 逻辑层
 * M6-A: Toast 通知 / spinner / 危险操作确认
 * M6-B: 状态双向同步 / WS cmd_result 更新 UI / 5s 轮询
 * M6-C: Lifting 三段控制 / VFD 档位 / 扫描 / RS485 日志浮窗
 *
 * 依赖：jQuery + api.js（已在页面先行加载）
 */

(function($, API) {
    'use strict';

    /* =========================================================
     * 1. Toast 通知
     * ========================================================= */
    var _toastTimer = null;

    function showToast(msg, type) {
        // type: 'success' | 'error' | 'info' | 'warn'
        var $t = $('#sslab-toast');
        if (!$t.length) return;
        $t.attr('data-type', type || 'info').text(msg).addClass('show');
        clearTimeout(_toastTimer);
        _toastTimer = setTimeout(function() {
            $t.removeClass('show');
        }, type === 'error' ? 5000 : 3000);
    }

    /* =========================================================
     * 2. Switch 带 spinner 的发送
     *    覆盖原有 .switch click 行为（追加，不替换音效逻辑）
     * ========================================================= */
    function sendSwitch($sw, state) {
        var id = $sw.attr('id');
        if (!id) return;
        var domain = (typeof getUrlParam1 === 'function') ? getUrlParam1(id) : 'JXDY';
        if (!domain) domain = 'JXDY';

        // 乐观 UI 已由原有代码处理（toggleClass active）
        // 这里只补 spinner + 结果 Toast
        $sw.addClass('sw-sending').attr('title', '发送中…');

        API.control(domain, id, state).then(function(res) {
            $sw.removeClass('sw-sending').attr('title', id);
            if (res.ok) {
                showToast(id + (state ? ' 已开启' : ' 已关闭'), 'success');
            } else {
                // 回滚开关状态（操作失败）
                if (state) { $sw.removeClass('active'); } else { $sw.addClass('active'); }
                showToast(id + ' 操作失败：' + res.error, 'error');
            }
        });
    }

    /* =========================================================
     * 3. 危险操作确认对话框
     *    HighKZ / HighCurrent 需要 3s 倒计时才能确认
     * ========================================================= */
    var DANGER_KEYS = { 'HighKZ': true, 'HighCurrent': true };
    var _confirmPending = null;

    function showDangerConfirm(id, onConfirm, onCancel) {
        var $dlg = $('#sslab-confirm-dlg');
        if (!$dlg.length) return onConfirm(); // 降级：无弹窗直接执行
        var $msg = $dlg.find('.confirm-msg');
        var $btn = $dlg.find('.confirm-ok');
        var $cnt = $dlg.find('.confirm-count');
        $msg.text('即将开启【' + id + '】高压设备，请确认操作');
        $btn.prop('disabled', true);
        var remain = 3;
        $cnt.text(remain);
        var timer = setInterval(function() {
            remain--;
            $cnt.text(remain);
            if (remain <= 0) {
                clearInterval(timer);
                $btn.prop('disabled', false);
                $cnt.text('');
            }
        }, 1000);
        _confirmPending = {
            onConfirm: function() {
                clearInterval(timer);
                $dlg.hide();
                _confirmPending = null;
                onConfirm();
            },
            onCancel: function() {
                clearInterval(timer);
                $dlg.hide();
                _confirmPending = null;
                if (onCancel) onCancel();
            }
        };
        $dlg.show();
    }

    /* =========================================================
     * 4. 覆盖 .switch click —— 追加 API 反馈
     *    原有逻辑仍执行（音效/倒计时），这里在其后拦截
     * ========================================================= */
    $(document).on('sslab:switch:clicked', function(e, id, state) {
        // 由修改后的原始 .switch click 触发
        if (DANGER_KEYS[id] && state) {
            // 先回滚，等确认后再正式发送
            var $sw = $('#' + id);
            $sw.toggleClass('active'); // 暂时撤销乐观 UI
            showDangerConfirm(id,
                function() {
                    // 确认：重新翻开关并发送
                    $sw.toggleClass('active');
                    sendSwitch($sw, state);
                },
                function() {
                    // 取消：什么都不做（已撤销 UI）
                    showToast('已取消操作', 'info');
                }
            );
        } else {
            sendSwitch($('#' + id), state);
        }
    });

    /* =========================================================
     * 5. settingInput 结果反馈（覆盖缺失的成功/失败提示）
     * ========================================================= */
    var _origSettingInput = window.settingInput;
    window.settingInput = function(id, val) {
        // 先执行原始验证逻辑（会 alert 并 return）
        if (_origSettingInput) {
            // 捕获验证失败（原始会 alert+return，这里无法拦截，保持原样）
            _origSettingInput.call(this, id, val);
        }
        // 补充 Toast（原始只 console.log 成功/失败）
        // 因为原始函数内部已经发出请求，这里无需重复发送
        // 只在原始函数没有 return 的情况下到达这里
    };

    /* =========================================================
     * 6. 状态同步：WS cmd_result → 更新 UI
     * ========================================================= */
    function applyStateToUI(dt) {
        // Lifting / Computer / VFD_Power
        ['Lifting', 'Computer', 'VFD_Power', 'LowKZ', 'LowDC_AC',
         'HighXZ', 'HighKZ', 'HighCurrent', 'PowerCZ', 'LowXSTB',
         'XS_A', 'XS_B', 'XS_C', 'XS_D', 'GSKZ', 'PFKZ',
         'BBLampKZ', 'CRLampKZ', 'CLQQ', 'CLHQ'
        ].forEach(function(key) {
            if (dt[key] === undefined) return;
            var val = dt[key];
            var b = (val === true || val === 1 || val === '1' || val === 'on' || val === 'up' || val === 'true');
            var $el = $('#' + key);
            if (!$el.length || !$el.hasClass('switch')) return;
            if (b) { $el.addClass('active'); } else { $el.removeClass('active'); }
        });

        // VFD_Speed
        if (dt.VFD_Speed !== undefined && window._VFD_highlightActive) {
            window._VFD_highlightActive(String(dt.VFD_Speed));
        }
        // Lifting 三段状态显示
        if (dt.Lifting !== undefined) {
            var ls = dt.Lifting;
            var liftLabel, liftColor;
            if (ls === 'up' || ls === true || ls === 1) {
                liftLabel = '▲ 上升'; liftColor = '#28a745';
            } else if (ls === 'down' || ls === false || ls === 0) {
                liftLabel = '▼ 下降'; liftColor = '#dc3545';
            } else {
                liftLabel = '■ 停止'; liftColor = '#ffc107';
            }
            var $tip = $('#liftStatusTip');
            if ($tip.length) {
                $tip.text(liftLabel).css('color', liftColor);
            }
        }
    }

    // 注入到 websocket.onmessage 的 cmd_result 分支
    var _origOnMessage = null;
    function patchWsOnMessage() {
        var ws = window.websocket;
        if (!ws) return;
        if (ws._sslab_patched) return;
        ws._sslab_patched = true;
        var origHandler = ws.onmessage;
        ws.onmessage = function(ev) {
            if (origHandler) origHandler.call(this, ev);
            // 额外处理 cmd_result：当后端返回 state 时同步 UI
            try {
                if (typeof ev.data === 'string') {
                    var msg = JSON.parse(ev.data);
                    if (msg.type === 'cmd_result' && msg.state) {
                        applyStateToUI(msg.state);
                    }
                }
            } catch(e) {}
        };
    }

    // 5 秒轮询 /req，保证多端状态同步 + 触发图表更新
    function startStatePolling() {
        setInterval(function() {
            API.getState().then(function(res) {
                if (res.ok && res.data) {
                    applyStateToUI(res.data);
                    // 触发图表更新（供 patch_charts.py 注入的图表模块消费）
                    try {
                        window.dispatchEvent(new CustomEvent('sslab:state:updated', { detail: res.data }));
                    } catch(e) {}
                    // 直接调用（兼容性备用）
                    if (window.SSLAB_CHARTS && typeof window.SSLAB_CHARTS.update === 'function') {
                        window.SSLAB_CHARTS.update(res.data);
                    }
                }
            });
        }, 5000);
    }

    /* =========================================================
     * 7. Lifting 三段控制面板增强
     *    HTML 已有三按钮，这里增强为使用新 API + 添加状态提示
     * ========================================================= */
    function initLiftingPanel() {
        var $btns = $('.lift-up-btn, .lift-stop-btn, .lift-down-btn');
        if (!$btns.length) return;
        if ($('#liftStatusTip').length) return; // 已初始化

        // 移除旧的 onclick 属性，改用事件委托
        $btns.removeAttr('onclick');

        // 添加状态提示文字
        var $boxTitle = $btns.closest('.left-box').find('.box-title');
        if ($boxTitle.length) {
            $boxTitle.append(' <span id="liftStatusTip" style="font-size:11px;color:#888;">● 等待控制</span>');
        }

        // 绑定新的事件处理
        $btns.on('click', function() {
            var $btn = $(this);
            var action;
            if ($btn.hasClass('lift-up-btn')) action = 'up';
            else if ($btn.hasClass('lift-stop-btn')) action = 'stop';
            else if ($btn.hasClass('lift-down-btn')) action = 'down';
            if (!action) return;

            var domain = 'SYHJ';
            if (typeof getUrlParam1 === 'function') domain = getUrlParam1('Lifting') || 'SYHJ';
            $btns.prop('disabled', true);

            // 记录操作日志
            var actionCN = {up:'上升', stop:'停止', down:'下降'};
            try { window.logOperation && window.logOperation('升降控制', actionCN[action]||action, 'pending'); } catch(_) {}

            API.control(domain, 'Lifting', action).then(function(res) {
                $btns.prop('disabled', false);
                if (res.ok) {
                    // 更新1053状态徽章
                    try {
                        var $badge = $('#status1053');
                        if ($badge.length) {
                            $badge.removeClass('disconnected').addClass('connected').text('● 已连接');
                        }
                    } catch(_) {}
                    var tips = { up: '▲ 正在上升', stop: '■ 已停止', down: '▼ 正在下降' };
                    var colors = { up: '#28a745', stop: '#ffc107', down: '#dc3545' };
                    $('#liftStatusTip').text(tips[action] || '').css('color', colors[action] || '#888');
                    showToast('升降 ' + action + ' 已发送', 'success');
                    try { window.logOperation && window.logOperation('升降控制', actionCN[action]||action, 'ok'); } catch(_) {}
                } else {
                    var errMsg = res.error || '';
                    var hint = '';
                    if (/disabled/i.test(errMsg)) {
                        hint = ' — 请在 <a href="/admin" target="_blank" style="color:#fff;text-decoration:underline">Admin后台</a> 启用 RS485';
                    } else if (/port|serial|com/i.test(errMsg) || /not found|cannot open/i.test(errMsg)) {
                        hint = ' — 请在 <a href="/admin" target="_blank" style="color:#fff;text-decoration:underline">Admin后台</a> 自动检测 COM 口';
                    }
                    var $t = $('#sslab-toast');
                    $t.attr('data-type', 'error').html('升降控制失败：' + errMsg + hint).addClass('show');
                    clearTimeout(window._liftToastTimer);
                    window._liftToastTimer = setTimeout(function() { $t.removeClass('show'); }, 6000);
                    $('#liftStatusTip').text('● 通信失败').css('color', '#dc3545');
                    try { window.logOperation && window.logOperation('升降控制', actionCN[action]||action, 'err'); } catch(_) {}
                }
            });
        });
    }

    /* =========================================================
     * 8. VFD 速度快捷档位按钮（直接使用 HTML 中的按钮，绑定事件）
     * ========================================================= */
    function initVFDPanel() {
        var $btns = $('.vfd-spd-btn');
        if (!$btns.length) return;

        // 高亮当前选中档位
        function highlightActive(spd) {
            $btns.removeClass('btn-primary').addClass('btn-default');
            $btns.filter('[data-spd="' + spd + '"]').removeClass('btn-default').addClass('btn-primary');
        }

        $btns.on('click', function() {
            var $btn = $(this);
            var spd = $btn.data('spd');
            var spdLabel = $btn.text().trim() || ('档位'+spd);
            var domain = 'SYHJ';
            if (typeof getUrlParam1 === 'function') domain = getUrlParam1('VFD_Speed') || 'SYHJ';
            $btn.prop('disabled', true);

            // 记录操作日志
            try { window.logOperation && window.logOperation('变频器档位', spdLabel, 'pending'); } catch(_) {}

            API.control(domain, 'VFD_Speed', Number(spd)).then(function(res) {
                $btn.prop('disabled', false);
                if (res.ok) {
                    highlightActive(spd);
                    showToast('变频器档位 ' + spd, 'success');
                    try { window.logOperation && window.logOperation('变频器档位', spdLabel, 'ok'); } catch(_) {}
                } else {
                    showToast('变频器失败：' + res.error, 'error');
                    try { window.logOperation && window.logOperation('变频器档位', spdLabel, 'err'); } catch(_) {}
                }
            });
        });

        // 暴露供状态同步使用
        window._VFD_highlightActive = highlightActive;
    }

    /* =========================================================
     * 9. 统一操作日志浮窗（RS485 + 所有控制操作）
     * ========================================================= */
    function initUnifiedLogPanel() {
        if ($('#sslab-log-panel').length) return;
        var html = '<div id="sslab-log-panel" style="display:none;position:fixed;bottom:70px;right:16px;'
            + 'width:520px;max-height:420px;overflow-y:auto;background:#1e1e1e;color:#d4d4d4;'
            + 'border-radius:10px;box-shadow:0 4px 24px rgba(0,0,0,.6);z-index:9998;font-size:12px;'
            + 'font-family:\'Consolas\',\'Microsoft YaHei\',monospace;padding:12px;">'
            + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;border-bottom:1px solid #333;padding-bottom:8px;">'
            + '<span style="font-weight:bold;color:#9cdcfe;font-size:13px;">📋 操作日志</span>'
            + '<span style="display:flex;gap:10px;align-items:center;">'
            + '<select id="sslab-log-filter" style="background:#2d2d2d;color:#ccc;border:1px solid #444;border-radius:4px;padding:2px 6px;font-size:11px;">'
            + '<option value="all">全部</option><option value="ok">✓ 成功</option><option value="err">✗ 失败</option><option value="pending">⏳ 进行中</option>'
            + '</select>'
            + '<span style="cursor:pointer;opacity:.6;font-size:14px;" id="sslab-log-close">✕</span>'
            + '</span>'
            + '</div>'
            + '<div id="sslab-log-body" style="max-height:340px;overflow-y:auto;">暂无记录</div>'
            + '</div>'
            + '<button id="sslab-log-btn" title="操作日志" style="position:fixed!important;left:18px!important;bottom:17px!important;'
            + 'width:44px!important;height:44px!important;border-radius:50%;background:#1e293b!important;border:none;color:#9cdcfe;'
            + 'font-size:11px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.35);z-index:9998!important;'
            + 'font-weight:700;display:inline-flex;align-items:center;justify-content:center;">LOG</button>';
        $('body').append(html);

        $('#sslab-log-btn').on('click', function() {
            var $p = $('#sslab-log-panel');
            if ($p.is(':visible')) {
                $p.hide();
            } else {
                $p.show();
                refreshUnifiedLog();
            }
        });
        $('#sslab-log-close').on('click', function() {
            $('#sslab-log-panel').hide();
        });
        $('#sslab-log-filter').on('change', function() {
            refreshUnifiedLog();
        });
    }

    function renderOpLogEntry(e) {
        var colors = {ok:'#4ec94e', err:'#f44747', pending:'#dcdcaa'};
        var icons = {ok:'✓', err:'✗', pending:'⏳'};
        var color = colors[e.status] || '#888';
        var icon = icons[e.status] || '?';
        return '<div style="border-bottom:1px solid #333;padding:3px 0;">'
            + '<span style="color:#888;">' + (e.ts || '') + '</span> '
            + '<span style="color:' + color + ';">' + icon + '</span> '
            + '<span style="color:#ce9178;">' + (e.action || '') + '</span> '
            + '<span style="color:#9cdcfe;">' + (e.detail || '') + '</span>'
            + '</div>';
    }

    function refreshUnifiedLog() {
        var $body = $('#sslab-log-body');
        var filter = $('#sslab-log-filter').val() || 'all';

        // 先渲染操作日志
        var opLog = window._opLog || [];
        var filteredOps = filter === 'all' ? opLog : opLog.filter(function(e) { return e.status === filter; });
        var opRows = filteredOps.map(renderOpLogEntry);

        // 尝试获取RS485日志并合并
        API.getRS485Log(20).then(function(res) {
            var rsRows = [];
            if (res.ok && res.data && res.data.log && res.data.log.length) {
                rsRows = res.data.log.map(function(e) {
                    var color = e.ok ? '#4ec94e' : '#f44747';
                    var tag = e.tag || '?';
                    var statIcon = e.ok ? '✓' : '✗';
                    var statStr = e.ok ? 'ok' : 'err';
                    var opEntry = {
                        ts: e.ts || '',
                        action: 'RS485:' + tag,
                        detail: (e.ms||0) + 'ms TX:' + (e.tx||'').substring(0,30) + (e.error?' ERR:'+(e.error||'').substring(0,20):''),
                        status: statStr
                    };
                    if (filter === 'all' || filter === statStr) {
                        return renderOpLogEntry(opEntry);
                    }
                    return null;
                }).filter(Boolean);
            }

            var allRows = opRows.concat(rsRows);
            if (!allRows.length) {
                $body.html('<div style="color:#888;text-align:center;padding:10px;">暂无匹配记录</div>');
            } else {
                $body.html(allRows.join(''));
            }
        }).catch(function() {
            // RS485日志不可用，只显示操作日志
            if (!opRows.length) {
                $body.html('<div style="color:#888;text-align:center;padding:10px;">暂无操作记录</div>');
            } else {
                $body.html(opRows.join(''));
            }
        });
    }

    /* =========================================================
     * 10. 扫描按钮注入（在 .status-badge 旁边注入扫描触发入口）
     * ========================================================= */
    function initScanButton() {
        if ($('#sslab-scan-btn').length) return;
        var $badge = $('#status1053');
        if (!$badge.length) return;
        var $btn = $('<button id="sslab-scan-btn" title="重新扫描设备" style="'
            + 'margin-left:6px;padding:1px 6px;font-size:10px;border-radius:4px;'
            + 'background:#007bff;color:#fff;border:none;cursor:pointer;vertical-align:middle;">扫描</button>');
        $badge.after($btn);

        $btn.on('click', function() {
            $btn.prop('disabled', true).text('…');
            try { window.logOperation && window.logOperation('设备扫描', '网络扫描', 'pending'); } catch(_) {}
            API.scan('1053', false).then(function(res) {
                $btn.prop('disabled', false).text('扫描');
                if (res.ok && res.data) {
                    var cnt = res.data.count || 0;
                    showToast('扫描完成，发现 ' + cnt + ' 台设备', 'success');
                    try { window.logOperation && window.logOperation('设备扫描', '发现' + cnt + '台', 'ok'); } catch(_) {}
                    if (res.data.devices && typeof parseAndRender === 'function') {
                        parseAndRender(res.data.devices);
                    }
                } else {
                    showToast('扫描失败：' + res.error, 'error');
                    try { window.logOperation && window.logOperation('设备扫描', '失败', 'err'); } catch(_) {}
                }
            });
        });
    }

    /* =========================================================
     * 11. WebSocket 连接断开顶部横幅
     * ========================================================= */
    function initWsBanner() {
        if ($('#sslab-ws-banner').length) return;
        var $banner = $('<div id="sslab-ws-banner" style="display:none;position:fixed;top:0;left:0;right:0;'
            + 'background:#dc3545;color:#fff;text-align:center;padding:6px;font-size:13px;z-index:99999;'
            + 'font-weight:bold;">⚠ 与后端的连接已断开，正在自动重连…</div>');
        $('body').prepend($banner);
    }

    // 由外部代码调用的接口
    window.SSLABAPP = {
        showToast: showToast,
        applyStateToUI: applyStateToUI,
        patchWsOnMessage: patchWsOnMessage,
        notifyWsOnline: function() { $('#sslab-ws-banner').hide(); },
        notifyWsOffline: function() { $('#sslab-ws-banner').show(); }
    };

    /* =========================================================
     * 12. 初始化入口
     * ========================================================= */
    $(function() {
        initLiftingPanel();
        initVFDPanel();
        initUnifiedLogPanel();
        initWsBanner();
        startStatePolling();

        // WS 初始化后补丁（等 connectWs 跑完）
        setTimeout(function() {
            patchWsOnMessage();
        }, 1500);

        // 确认弹窗按钮事件
        $(document).on('click', '#sslab-confirm-ok', function() {
            if (_confirmPending) _confirmPending.onConfirm();
        });
        $(document).on('click', '#sslab-confirm-cancel', function() {
            if (_confirmPending) _confirmPending.onCancel();
        });
    });

})(jQuery, window.SSLABAPI || {});
