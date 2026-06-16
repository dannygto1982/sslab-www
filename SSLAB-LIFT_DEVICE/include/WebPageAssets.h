#pragma once

#include <Arduino.h>

namespace WebPageAssets {

const char kCss[] = R"(
<style>
:root{--bg:#eef2ff;--card:#ffffff;--primary:#4f46e5;--primary-dark:#4338ca;--text:#1f2937;--muted:#6b7280;--border:#e5e7eb;--success:#10b981;--warning:#f59e0b;--danger:#ef4444;}
*{box-sizing:border-box;}
body{margin:0;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);}
a{color:inherit;text-decoration:none;}
header.brand{display:flex;align-items:center;gap:1rem;margin-bottom:2rem;} 
.page{max-width:1080px;margin:0 auto;padding:2.5rem 1.5rem;} 
.brand-logo{width:60px;height:60px;border-radius:18px;background:linear-gradient(135deg,var(--primary),#6366f1);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:22px;color:#fff;box-shadow:0 12px 30px rgba(79,70,229,0.25);} 
.brand-title{display:flex;flex-direction:column;gap:0.35rem;} 
.brand-title h1{margin:0;font-size:28px;color:var(--text);} 
.brand-title p{margin:0;color:var(--muted);letter-spacing:0.12em;font-size:13px;text-transform:uppercase;} 
.card{background:var(--card);border-radius:18px;padding:2rem;box-shadow:0 12px 30px rgba(79,70,229,0.12);border:1px solid var(--border);margin-bottom:1.75rem;} 
.card h2{margin:0;font-size:20px;color:var(--text);} 
.status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-top:1.25rem;} 
.status-pill{display:flex;flex-direction:column;gap:0.35rem;padding:1rem;border-radius:14px;background:rgba(79,70,229,0.08);color:var(--text);font-size:14px;} 
.status-pill strong{font-size:13px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:0.08em;} 
label{display:flex;flex-direction:column;gap:0.5rem;font-size:13px;color:var(--muted);} 
input{padding:12px 14px;border:1px solid var(--border);border-radius:12px;background:#fff;color:var(--text);font-size:15px;transition:border-color .2s,box-shadow .2s;} 
input:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px rgba(79,70,229,0.18);} 
.grid-two{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.5rem;margin-top:1.5rem;} 
.hint{font-size:12px;color:var(--muted);} 
.primary-btn{margin-top:2rem;display:inline-flex;align-items:center;gap:0.5rem;padding:0.85rem 2.4rem;border-radius:999px;border:none;background:linear-gradient(135deg,var(--primary),#6366f1);color:#fff;font-weight:600;font-size:15px;cursor:pointer;transition:transform .2s,box-shadow .2s;box-shadow:0 14px 28px rgba(79,70,229,0.24);} 
.primary-btn:hover{transform:translateY(-1px);box-shadow:0 18px 32px rgba(79,70,229,0.28);background:linear-gradient(135deg,var(--primary-dark),var(--primary));} 
.simulate-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:0.75rem;margin-top:1.25rem;} 
.simulate-grid button{padding:0.75rem 1rem;border-radius:12px;border:1px solid rgba(79,70,229,0.2);background:rgba(79,70,229,0.08);color:var(--primary);font-weight:600;cursor:pointer;transition:background .2s,border-color .2s,transform .2s;} 
.simulate-grid button:hover{background:rgba(79,70,229,0.14);border-color:rgba(79,70,229,0.35);transform:translateY(-1px);} 
.simulate-grid button.busy{opacity:0.6;cursor:wait;} 
pre{margin-top:1.5rem;padding:1.2rem;border-radius:14px;background:#0f172a0d;border:1px solid rgba(79,70,229,0.1);font-size:13px;font-family:'JetBrains Mono','SFMono-Regular',monospace;min-height:90px;white-space:pre-wrap;word-break:break-all;} 
footer{text-align:center;font-size:13px;color:var(--muted);margin-top:2.5rem;} 
.toast{position:fixed;right:1.5rem;bottom:1.5rem;padding:0.85rem 1.4rem;border-radius:12px;background:var(--card);border:1px solid var(--border);box-shadow:0 16px 32px rgba(15,23,42,0.18);font-size:14px;color:var(--text);opacity:0;transform:translateY(10px);pointer-events:none;transition:opacity .25s ease,transform .25s ease;} 
.toast.show{opacity:1;transform:translateY(0);} 
.toast[data-type="success"]{border-color:rgba(16,185,129,0.4);box-shadow:0 16px 32px rgba(16,185,129,0.18);} 
.toast[data-type="error"]{border-color:rgba(239,68,68,0.4);box-shadow:0 16px 32px rgba(239,68,68,0.18);} 
@media(max-width:640px){.page{padding:2rem 1.25rem;}header.brand{flex-direction:column;align-items:flex-start;} .brand-logo{width:54px;height:54px;} .primary-btn{width:100%;justify-content:center;} .status-grid{grid-template-columns:1fr;} .grid-two{grid-template-columns:1fr;}}
</style>
)";

const char kJs[] = R"(
<script>
(function(){
    const resultBox=document.getElementById('simulateResult');
    const toast=document.getElementById('toast');
    const mqttState=document.getElementById('mqttState');
    const mqttUptime=document.getElementById('mqttUptime');
    const mqttError=document.getElementById('mqttError');
    const logContainer=document.getElementById('logContainer');
    
    function showToast(message,type){
        toast.textContent=message;
        toast.dataset.type=type||'info';
        toast.hidden=false;
        toast.classList.remove('show');
        void toast.offsetWidth;
        toast.classList.add('show');
        clearTimeout(showToast.timer);
        showToast.timer=setTimeout(()=>toast.classList.remove('show'),2600);
    }
    
    function formatUptime(ms){
        if(ms<=0)return '-';
        const s=Math.floor(ms/1000);
        const m=Math.floor(s/60);
        const h=Math.floor(m/60);
        const d=Math.floor(h/24);
        if(d>0)return d+'天 '+h%24+'小时';
        if(h>0)return h+'小时 '+m%60+'分';
        if(m>0)return m+'分 '+s%60+'秒';
        return s+'秒';
    }
    
    async function refreshStatus(){
        try{
            const resp=await fetch('/api/status');
            const data=await resp.json();
            mqttState.textContent=data.mqtt.connected?'🟢 已连接':'🔴 未连接';
            mqttState.style.color=data.mqtt.connected?'var(--success)':'var(--danger)';
            mqttUptime.textContent=formatUptime(data.mqtt.uptime);
            mqttError.textContent=data.mqtt.lastError||'-';
            
            // 更新设备运行时状态（操作成功判断依据）
            if(data.device){
                var devEl=document.getElementById('devStateGrid');
                if(devEl){
                    var c=!!data.device.computer?'<span style="color:var(--success);">● 已开启</span>':'<span style="color:var(--muted);">○ 已关闭</span>';
                    var liftLabel={'up':'▲ 上升','down':'▼ 下降','stop':'■ 停止'};
                    var l=liftLabel[data.device.lifting]||'■ 停止';
                    var lamp=!!data.device.lamp?'<span style="color:var(--success);">💡 亮</span>':'<span style="color:var(--muted);">🌑 灭</span>';
                    var lastTs=data.device.lastUpdateMs? Math.floor(data.device.lastUpdateMs/1000)+'s前' : '--';
                    devEl.innerHTML='<div class="status-pill"><strong>电脑</strong><span>'+c+'</span></div>'
                        +'<div class="status-pill"><strong>升降</strong><span>'+l+'</span></div>'
                        +'<div class="status-pill"><strong>灯光</strong><span>'+lamp+'</span></div>'
                        +'<div class="status-pill"><strong>最后更新</strong><span>'+lastTs+'</span></div>';
                }
            }
            
            // 更新 RS485 最后帧信息
            if(data.rs485){
                var rs485El=document.getElementById('rs485Info');
                if(rs485El && data.rs485.lastFrameLen>0){
                    rs485El.innerHTML='<span style="font-size:12px;color:var(--muted);">最后RS485帧: '+data.rs485.lastFrameLen+'B ['+data.rs485.lastFrameHex+']</span>';
                }
            }
            
            if(data.logs&&data.logs.length>0){
                logContainer.innerHTML=data.logs.map(log=>{
                    const color=log.level==='ERROR'?'#ef4444':log.level==='WARN'?'#f59e0b':'#6b7280';
                    return `<div style="margin-bottom:0.5rem;"><span style="color:${color};font-weight:600;">[${log.level}]</span> <span style="color:#94a3b8;">${log.timestamp}</span> ${log.message}</div>`;
                }).join('');
            }else{
                logContainer.innerHTML='<div style="color:#94a3b8;">暂无日志</div>';
            }
        }catch(err){
            console.error('Status refresh failed:',err);
            if(logContainer.textContent.includes('正在加载')){
                 logContainer.innerHTML='<div style="color:#ef4444;">加载失败: '+err.message+'</div>';
            }
        }
    }
    
    document.querySelectorAll('.simulate-grid button').forEach(btn=>{
        btn.addEventListener('click',async()=>{
            const action=btn.dataset.action;
            resultBox.textContent='执行中...';
            btn.disabled=true;
            btn.classList.add('busy');
            try{
                const resp=await fetch('/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
                const data=await resp.json();
                resultBox.textContent=JSON.stringify(data,null,2);
                showToast('动作已模拟','success');
            }catch(err){
                resultBox.textContent='请求失败: '+err;
                showToast('请求失败','error');
            }finally{
                btn.disabled=false;
                btn.classList.remove('busy');
            }
        });
    });
    
    refreshStatus();
    setInterval(refreshStatus,5000);
})();
</script>
)";

inline String getHeader(const String& title) {
    String h = F("<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"UTF-8\">");
    h += F("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">");
    h += F("<title>");
    h += title;
    h += F("</title>");
    h += F("<link rel=\"stylesheet\" href=\"/style.css\" media=\"print\" onload=\"this.media='all'\">");
    h += F("</head><body><div class=\"page\">");
    h += F("<header class=\"brand\"><div class=\"brand-logo\">SL</div><div class=\"brand-title\"><h1>");
    h += title;
    h += F("</h1><p>Smart Space Laboratory</p></div></header>");
    return h;
}

inline String getFooter() {
    String f = F("<footer>© 2025 SSLAB Smart Space • Intelligent Control System</footer>");
    f += F("<div id=\"toast\" class=\"toast\" hidden></div>");
    f += F("<script src=\"/app.js\" defer></script>");
    f += F("</div></body></html>");
    return f;
}

// 提取纯 CSS 内容（去掉 <style> 包裹标签），供独立路由使用
// 使用 static 缓存避免每次请求重复 2.8KB 的 substring 复制
inline String getCssContent() {
    static String cached;
    if (cached.length() == 0) {
        String s(kCss);
        int start = s.indexOf("<style>") + 7;
        int end = s.lastIndexOf("</style>");
        cached = s.substring(start, end);
    }
    return cached;
}

// 提取纯 JS 内容（去掉 <script> 包裹标签），供独立路由使用
// 使用 static 缓存避免每次请求重复 3.5KB 的 substring 复制
inline String getJsContent() {
    static String cached;
    if (cached.length() == 0) {
        String s(kJs);
        int start = s.indexOf("<script>") + 8;
        int end = s.lastIndexOf("</script>");
        cached = s.substring(start, end);
    }
    return cached;
}

} // namespace WebPageAssets
