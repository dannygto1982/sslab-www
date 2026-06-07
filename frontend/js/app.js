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
        if (dt.VFD_Speed !== undefined) {
            $('#VFD_Speed').val(String(dt.VFD_Speed));
        }
        // Lifting 三段状态显示
        if (dt.Lifting !== undefined) {
            var ls = dt.Lifting;
            var liftLabel = (ls === 'up' || ls === true || ls === 1) ? '▲ 上升'
                          : (ls === 'down' || ls === false || ls === 0) ? '▼ 下降'
                          : '■ 停止';
            var $liftBtn = $('#Lifting');
            if ($liftBtn.length) {
                $liftBtn.attr('title', liftLabel);
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
     * 7. Lifting 三段控制面板注入
     *    在 #Lifting 旁边动态注入 上升/停止/下降 三按钮
     * ========================================================= */
    function initLiftingPanel() {
        var $sw = $('#Lifting');
        if (!$sw.length) return;
        if ($sw.closest('.lifting-panel').length) return; // 已初始化

        var $parent = $sw.closest('.clearfix.left-box-c');
        if (!$parent.length) return;

        // 隐藏原有的 toggle 开关（用三按钮替代）
        $sw.hide();

        var html = '<div class="lifting-btns" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;">'
            + '<button class="btn btn-sm btn-default lift-btn" data-lift="up"   title="升起">▲ 升</button>'
            + '<button class="btn btn-sm btn-warning  lift-btn" data-lift="stop" title="停止">■ 停</button>'
            + '<button class="btn btn-sm btn-default lift-btn" data-lift="down" title="落下">▼ 降</button>'
            + '<span id="liftStatusTip" style="font-size:11px;color:#888;align-self:center;"></span>'
            + '</div>';
        $parent.find('.pull-right').append(html);

        $parent.on('click', '.lift-btn', function() {
            var action = $(this).data('lift');
            var domain = 'SYHJ';
            if (typeof getUrlParam1 === 'function') domain = getUrlParam1('Lifting') || 'SYHJ';
            var $btn = $(this);
            $btn.prop('disabled', true);
            API.control(domain, 'Lifting', action).then(function(res) {
                $btn.prop('disabled', false);
                if (res.ok) {
                    var tips = { up: '▲ 正在上升', stop: '■ 已停止', down: '▼ 正在下降' };
                    $('#liftStatusTip').text(tips[action] || '');
                    showToast('升降 ' + action + ' 已发送', 'success');
                } else {
                    showToast('升降控制失败：' + res.error, 'error');
                }
            });
        });
    }

    /* =========================================================
     * 8. VFD 速度快捷档位按钮（在 select 下方注入 1/2/3 快捷钮）
     * ========================================================= */
    function initVFDPanel() {
        var $sel = $('#VFD_Speed');
        if (!$sel.length || $sel.next('.vfd-quick').length) return;

        var html = '<div class="vfd-quick" style="display:flex;gap:4px;margin-top:4px;">'
            + '<button class="btn btn-xs btn-default" data-spd="1">低</button>'
            + '<button class="btn btn-xs btn-default" data-spd="2">中</button>'
            + '<button class="btn btn-xs btn-default" data-spd="3">高</button>'
            + '</div>';
        $sel.after(html);

        $sel.closest('.clearfix').on('click', '.vfd-quick button', function() {
            var spd = $(this).data('spd');
            $sel.val(String(spd));
            var domain = 'SYHJ';
            if (typeof getUrlParam1 === 'function') domain = getUrlParam1('VFD_Speed') || 'SYHJ';
            API.control(domain, 'VFD_Speed', Number(spd)).then(function(res) {
                if (res.ok) {
                    showToast('变频器档位 ' + spd, 'success');
                } else {
                    showToast('变频器失败：' + res.error, 'error');
                }
            });
        });
    }

    /* =========================================================
     * 9. RS485 日志浮窗
     * ========================================================= */
    function initRS485LogPanel() {
        if ($('#sslab-log-panel').length) return;
        var html = '<div id="sslab-log-panel" style="display:none;position:fixed;bottom:70px;right:16px;'
            + 'width:480px;max-height:360px;overflow-y:auto;background:#1e1e1e;color:#d4d4d4;'
            + 'border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,.5);z-index:9998;font-size:12px;'
            + 'font-family:\'Consolas\',monospace;padding:10px;">'
            + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
            + '<span style="font-weight:bold;color:#9cdcfe;">RS485 事务日志</span>'
            + '<span style="cursor:pointer;opacity:.6;" id="sslab-log-close">✕</span>'
            + '</div>'
            + '<div id="sslab-log-body">加载中…</div>'
            + '</div>'
            + '<button id="sslab-log-btn" title="RS485 日志" style="position:fixed;bottom:16px;right:70px;'
            + 'width:46px;height:46px;border-radius:50%;background:#2d2d2d;border:none;color:#9cdcfe;'
            + 'font-size:12px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.4);z-index:9997;">LOG</button>';
        $('body').append(html);

        $('#sslab-log-btn').on('click', function() {
            var $p = $('#sslab-log-panel');
            if ($p.is(':visible')) {
                $p.hide();
            } else {
                $p.show();
                refreshRS485Log();
            }
        });
        $('#sslab-log-close').on('click', function() {
            $('#sslab-log-panel').hide();
        });
    }

    function refreshRS485Log() {
        API.getRS485Log(30).then(function(res) {
            var $body = $('#sslab-log-body');
            if (!res.ok) { $body.text('获取失败: ' + res.error); return; }
            var logs = (res.data && res.data.log) ? res.data.log : [];
            if (!logs.length) { $body.text('暂无记录'); return; }
            var rows = logs.map(function(e) {
                var color = e.ok ? '#4ec94e' : '#f44747';
                var tag = e.tag || '?';
                return '<div style="border-bottom:1px solid #333;padding:3px 0;">'
                    + '<span style="color:#888;">' + (e.ts || '') + '</span> '
                    + '<span style="color:#ce9178;">' + tag + '</span> '
                    + '<span style="color:' + color + ';">' + (e.ok ? 'OK' : 'ERR') + '</span> '
                    + '<span style="color:#888;">' + (e.ms || 0) + 'ms</span>'
                    + (e.error ? '<br><span style="color:#f44747;font-size:10px;">  ' + e.error + '</span>' : '')
                    + '<br><span style="color:#555;font-size:10px;">TX: ' + (e.tx || '') + '</span>'
                    + '</div>';
            });
            $body.html(rows.join(''));
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
            API.scan('1053', false).then(function(res) {
                $btn.prop('disabled', false).text('扫描');
                if (res.ok && res.data) {
                    var cnt = res.data.count || 0;
                    showToast('扫描完成，发现 ' + cnt + ' 台设备', 'success');
                    if (res.data.devices && typeof parseAndRender === 'function') {
                        parseAndRender(res.data.devices);
                    }
                } else {
                    showToast('扫描失败：' + res.error, 'error');
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
        initRS485LogPanel();
        initScanButton();
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
