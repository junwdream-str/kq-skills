#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
滨康大区经理日报汇总：取数 -> 计算 -> 出图/出表

用法:
  python binkang_report.py --start 2026-09-07 --end 2026-09-09 --out report.html
  python binkang_report.py --start 2026-09-07 --end 2026-09-09 --format table
  python binkang_report.py --start 2026-09-07 --end 2026-09-09 --format json

口径:
  日增量 = 当日累计 - 前一日累计（首日即累计值）
  周累计 = 本周最后一次提交的累计值
  目标   = 本周首次填报值
  未提交 = 全 0 且计入分母
"""

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys

TARGETS = ['杨成长', '陈阳', '李丛恩', '叶占国', '汪洋',
           '杨万鹏', '李双伟', '纪昌波', '李继锋', '许森林']

FIELDS = [
    '本周发货目标（万）', '累计发货金额（万）',
    '本周试验目标（个）', '累计完成试验（个）',
    '本周会议目标（个）', '累计完成会议（个）',
    '本周回访试验/用户目标（个）', '累计完成回访（个）',
    '本周自媒体目标（个）', '累计完成自媒体（个）',
    '今日拜访零售店数量（个）',
]
TGT_IDX = [0, 2, 4, 6, 8]      # 目标列
CUM_IDX = [1, 3, 5, 7, 9]      # 累计完成列
DAY_IDX = 10                    # 当日口径
METRICS = ['发货', '试验', '会议', '回访', '自媒体']
SERIES = METRICS + ['拜访零售店']
UNITS = ['万', '个', '个', '个', '个', '个']


def _find_node():
    cands = []
    if os.environ.get('DWS_NODE'):
        cands.append(os.environ['DWS_NODE'])
    base = os.path.expanduser('~/.workbuddy/binaries/node/versions')
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            for nm in ('node.exe', 'node'):
                p = os.path.join(base, v, nm)
                if os.path.exists(p):
                    cands.append(p)
    cands.append('node')
    for c in cands:
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        elif shutil.which(c):
            return c
    return 'node'


def _find_dws_js():
    if os.environ.get('DWS_JS') and os.path.exists(os.environ['DWS_JS']):
        return os.environ['DWS_JS']
    roots = [os.path.expanduser('~/.workbuddy/binaries/node/cli-connector-packages'),
             os.path.expanduser('~/.workbuddy/binaries/node/workspace')]
    for r in roots:
        if not os.path.isdir(r):
            continue
        p = os.path.join(r, 'node_modules', 'dingtalk-workspace-cli', 'bin', 'dws.js')
        if os.path.exists(p):
            return p
        g = glob.glob(os.path.join(r, '**', 'dingtalk-workspace-cli', 'bin', 'dws.js'),
                      recursive=True)
        if g:
            return g[0]
    return None


def _build_cmd(args):
    """dws 在 Windows 上是 shell 脚本，Python 无法直接执行，需还原成 node + dws.js。"""
    js = _find_dws_js()
    if js:
        return [_find_node(), js] + args
    return ['dws'] + args


def run_dws(args):
    try:
        r = subprocess.run(_build_cmd(args + ['--format', 'json']),
                           capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=90)
        return r.stdout or ''
    except Exception as e:
        print('[warn] dws 调用失败: %s' % e, file=sys.stderr)
        return ''


def num(v):
    if v is None:
        return 0.0
    s = re.sub(r'[^0-9.\-]', '', str(v))
    try:
        return float(s)
    except Exception:
        return 0.0


def day_range(start, end):
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    out = []
    while s <= e:
        out.append(s.isoformat())
        s += dt.timedelta(days=1)
    return out


def find_ids(day):
    """翻页定位固定 10 人在某日的日志 ID。"""
    ids, cursor = {}, 0
    while cursor <= 200:
        out = run_dws(['report', 'inbox', 'list',
                       '--start', '%sT00:00:00+08:00' % day,
                       '--end', '%sT23:59:59+08:00' % day,
                       '--size', '20', '--cursor', str(cursor)])
        chunks = re.findall(r'\{[^{}]*"发送人"[^{}]*\}', out) if out else []
        if not chunks:
            break
        for p in chunks:
            try:
                o = json.loads(p)
            except Exception:
                continue
            name = str(o.get('发送人'))
            if name not in TARGETS or name in ids:
                continue
            m = re.search(r'id%3D([0-9a-f]{16,})', o.get('钉钉链接', ''))
            if m:
                ids[name] = m.group(1)
        if len(chunks) < 20:
            break
        cursor += 20
    return ids


def fetch(rid):
    out = run_dws(['report', 'entry', 'get', '--report-id', rid])
    if not out.strip().startswith('{'):
        return None, None
    try:
        res = json.loads(out).get('result') or {}
    except Exception:
        return None, None
    cells = {}
    for x in res.get('report_content', []):
        cells[x.get('key')] = (x.get('value') or '').strip()
    name = res.get('creatorName')
    if name not in TARGETS:
        return None, None
    return name, [num(cells.get(k)) for k in FIELDS]


def collect(days):
    data = {d: {} for d in days}
    for d in days:
        ids = find_ids(d)
        for n, rid in ids.items():
            name, vals = fetch(rid)
            if name:
                data[d][name] = vals
        print('[info] %s  命中 %d/%d' % (d, len(data[d]), len(TARGETS)))
    return data


def compute(data, days):
    daily = {}
    for i, d in enumerate(days):
        rows = {}
        prev_day = days[i - 1] if i > 0 else None
        for n in TARGETS:
            cur = data[d].get(n)
            if cur is None:
                rows[n] = None
                continue
            prev = data[prev_day].get(n) if prev_day else None
            base = prev if prev is not None else [0.0] * 11
            inc = [round(cur[c] - base[c], 2) for c in CUM_IDX]
            inc.append(round(cur[DAY_IDX], 2))
            rows[n] = inc
        daily[d] = rows

    weekly = {}
    for n in TARGETS:
        present = [d for d in days if data[d].get(n) is not None]
        if not present:
            weekly[n] = {'target': [0.0] * 5, 'done': [0.0] * 5, 'days': 0}
            continue
        first = data[present[0]][n]
        last = data[present[-1]][n]
        weekly[n] = {'target': [first[i] for i in TGT_IDX],
                     'done': [last[i] for i in CUM_IDX],
                     'days': len(present)}

    total_t = [0.0] * 5
    total_d = [0.0] * 5
    for n in TARGETS:
        for i in range(5):
            total_t[i] += weekly[n]['target'][i]
            total_d[i] += weekly[n]['done'][i]
    rate = [round(total_d[i] / total_t[i] * 100) if total_t[i] else 0
            for i in range(5)]
    return daily, weekly, {'target': total_t, 'done': total_d, 'rate': rate}


def anomalies(data, daily, days):
    out = []
    for n in TARGETS:
        miss = [d for d in days if data[d].get(n) is None]
        if miss:
            out.append('%s：%s 未提交，已按 0 计入' %
                       (n, '、'.join(m[5:] for m in miss)))
        for i, d in enumerate(days):
            if i == 0 or data[d].get(n) is None:
                continue
            prev = data[days[i - 1]].get(n)
            cur = data[d][n]
            if prev is None:
                continue
            back = []
            for k, c in enumerate(CUM_IDX):
                if cur[c] < prev[c]:
                    back.append('%s %g' % (METRICS[k], round(cur[c] - prev[c], 2)))
            if back:
                out.append('%s：%s 累计回退（%s）' % (n, d[5:], '、'.join(back)))
            inc = daily[d].get(n)
            if inc and all(abs(v) < 1e-9 for v in inc):
                out.append('%s：%s 六项增量全为 0，建议核实是否漏填' % (n, d[5:]))
    return out


def fmt(v):
    if abs(v - round(v)) < 1e-9:
        return '%d' % int(round(v))
    return '%.2f' % v


def render_table(daily, weekly, total, days):
    L = []
    L.append('## 日总结 · 当日增量\n')
    for d in days:
        L.append('### %s\n' % d)
        L.append('| 姓名 | ' + ' | '.join('%s(%s)' % (SERIES[i], UNITS[i]) for i in range(6)) + ' |')
        L.append('|---|' + '---:|' * 6)
        tot = [0.0] * 6
        for n in TARGETS:
            inc = daily[d].get(n)
            if inc is None:
                L.append('| %s 未提交 | 0 | 0 | 0 | 0 | 0 | 0 |' % n)
                continue
            for i in range(6):
                tot[i] += inc[i]
            L.append('| %s | %s |' % (n, ' | '.join(fmt(v) for v in inc)))
        L.append('| **合计** | %s |\n' % ' | '.join('**%s**' % fmt(v) for v in tot))
    L.append('## 周总结\n')
    L.append('| 指标 | 目标 | 完成 | 达成率 |')
    L.append('|---|---:|---:|---:|')
    for i in range(5):
        L.append('| %s（%s） | %s | %s | %d%% |' %
                 (METRICS[i], UNITS[i], fmt(total['target'][i]),
                  fmt(total['done'][i]), total['rate'][i]))
    return '\n'.join(L)


CSS = """
:root{--bg:#0d1117;--card:#161b22;--card2:#1c2230;--line:#2a3140;
--tx:#e6edf3;--tx2:#9aa7b8;--tx3:#6e7d90;--ac:#4c8dff;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
padding:32px 20px 64px;line-height:1.6}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:24px;font-weight:600}
.sub{color:var(--tx2);font-size:13px;margin-top:6px}
.meta{color:var(--tx3);font-size:12px;margin-top:4px}
section{margin-top:34px}
h2{font-size:16px;font-weight:600;margin-bottom:6px;padding-left:10px;border-left:3px solid var(--ac)}
.desc{font-size:12.5px;color:var(--tx3);margin:0 0 14px 13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px 12px 8px}
.chart{width:100%;height:340px}
.tabs{display:flex;gap:8px;margin:0 0 12px 4px;flex-wrap:wrap}
.tab{background:var(--card2);border:1px solid var(--line);color:var(--tx2);
padding:5px 14px;border-radius:14px;font-size:12.5px;cursor:pointer;transition:.15s}
.tab:hover{color:var(--tx);border-color:#3a4152}
.tab.on{background:rgba(76,141,255,.16);border-color:var(--ac);color:var(--ac);font-weight:500}
.note{background:var(--card2);border:1px solid var(--line);border-left:3px solid var(--warn);
border-radius:6px;padding:12px 16px;font-size:12.5px;color:var(--tx2);margin-top:26px}
.note b{color:var(--tx)}
footer{margin-top:32px;color:var(--tx3);font-size:11.5px;line-height:1.8;
border-top:1px solid var(--line);padding-top:14px}
#err{display:none;background:rgba(248,81,73,.1);border:1px solid var(--bad);
color:var(--bad);padding:14px 18px;border-radius:6px;font-size:13px;margin-top:20px}
"""

JS = """
var TX='#e6edf3',TX2='#9aa7b8',TX3='#6e7d90',LINE='#2a3140';
var OK='#3fb950',WARN='#d29922',BAD='#f85149',AC='#4c8dff',PU='#a371f7';
var M=__METRICS__,DAYS=__DAYS__,RATE=__RATE__,PROG=__PROG__;
var T2=__T2__,D2=__D2__,INC=__INC__,PPL=__PPL__,P4=__P4__;
var base={backgroundColor:'transparent',
 textStyle:{color:TX,fontFamily:'-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif'},
 tooltip:{trigger:'axis',axisPointer:{type:'shadow'},backgroundColor:'#1c2230',
 borderColor:LINE,textStyle:{color:TX,fontSize:12}},
 grid:{left:60,right:60,top:50,bottom:44}};
function ax(n,o){return Object.assign({type:'value',name:n,
 nameTextStyle:{color:TX3,fontSize:11},axisLine:{show:false},axisTick:{show:false},
 axisLabel:{color:TX3,fontSize:11},splitLine:{lineStyle:{color:'#1f2531'}}},o||{});}
function cat(d,o){return Object.assign({type:'category',data:d,
 axisLine:{lineStyle:{color:LINE}},axisTick:{show:false},
 axisLabel:{color:TX2,fontSize:12}},o||{});}

echarts.init(document.getElementById('c1')).setOption(Object.assign({},base,{
 legend:{data:['达成率'],top:6,right:10,textStyle:{color:TX2,fontSize:12},itemWidth:14,itemHeight:8},
 xAxis:cat(M),yAxis:ax('达成率 %',{max:100}),
 series:[{name:'达成率',type:'bar',data:RATE,barWidth:'46%',
  itemStyle:{borderRadius:[4,4,0,0],color:function(p){
   return p.value>=PROG?OK:(p.value>=PROG-8?WARN:BAD);}},
  label:{show:true,position:'top',color:TX2,fontSize:11,formatter:'{c}%'},
  markLine:{silent:true,symbol:'none',data:[{yAxis:PROG,
   lineStyle:{color:TX3,type:'dashed',width:1.5},
   label:{formatter:'时间进度 '+PROG+'%',color:TX2,fontSize:11,position:'insideEndTop'}}]}}]}));

echarts.init(document.getElementById('c2')).setOption(Object.assign({},base,{
 legend:{data:['目标','完成'],top:6,right:10,textStyle:{color:TX2,fontSize:12},itemWidth:14,itemHeight:8},
 grid:[{left:60,width:'15%',top:50,bottom:44},{left:'26%',right:64,top:50,bottom:44}],
 xAxis:[cat(['发货'],{gridIndex:0}),cat(M.slice(1),{gridIndex:1})],
 yAxis:[ax('万',{gridIndex:0}),ax('个',{gridIndex:1,position:'right'})],
 series:[
  {name:'目标',type:'bar',data:[T2[0]],barWidth:'26%',xAxisIndex:0,yAxisIndex:0,
   itemStyle:{color:'rgba(76,141,255,.35)',borderColor:AC,borderWidth:1,borderRadius:[4,4,0,0]}},
  {name:'完成',type:'bar',data:[D2[0]],barWidth:'26%',xAxisIndex:0,yAxisIndex:0,
   itemStyle:{color:AC,borderRadius:[4,4,0,0]}},
  {name:'目标',type:'bar',data:T2.slice(1),barWidth:'26%',xAxisIndex:1,yAxisIndex:1,
   itemStyle:{color:'rgba(163,113,247,.3)',borderColor:PU,borderWidth:1,borderRadius:[4,4,0,0]}},
  {name:'完成',type:'bar',data:D2.slice(1),barWidth:'26%',xAxisIndex:1,yAxisIndex:1,
   itemStyle:{color:PU,borderRadius:[4,4,0,0]}}],
 tooltip:{trigger:'axis',axisPointer:{type:'shadow'},backgroundColor:'#1c2230',
  borderColor:LINE,textStyle:{color:TX,fontSize:12},
  formatter:function(ps){var s=ps[0].axisValue+'<br/>';
   ps.forEach(function(p){s+=p.marker+p.seriesName+'：'+p.data+'<br/>';});return s;}}}));

var COL=[AC,PU,WARN,OK,'#ec6cb9','#39c5cf'];
var S3=[];
for(var i=0;i<6;i++){
 S3.push({name:SERIESNAME[i],type:'line',data:INC[i],yAxisIndex:i===0?0:1,smooth:false,
  symbol:'circle',symbolSize:7,lineStyle:{width:i===0?3:2,color:COL[i]},
  itemStyle:{color:COL[i]}});
}
echarts.init(document.getElementById('c3')).setOption(Object.assign({},base,{
 legend:{top:6,right:10,textStyle:{color:TX2,fontSize:12},itemWidth:16,itemHeight:8},
 grid:{left:60,right:64,top:50,bottom:44},
 xAxis:cat(DAYS),yAxis:[ax('发货 万'),ax('个',{splitLine:{show:false}})],series:S3}));

var c4=echarts.init(document.getElementById('c4'));
function draw4(k){
 var o=P4[k];
 c4.setOption(Object.assign({},base,{
  legend:{data:['目标','完成'],top:6,right:10,textStyle:{color:TX2,fontSize:12},itemWidth:14,itemHeight:8},
  grid:{left:70,right:70,top:50,bottom:34},
  xAxis:ax(o.n),
  yAxis:cat(PPL.slice().reverse(),{axisLabel:{color:TX2,fontSize:12}}),
  series:[{name:'目标',type:'bar',data:o.t.slice().reverse(),barWidth:'32%',
    itemStyle:{color:'rgba(76,141,255,.3)',borderColor:AC,borderWidth:1,borderRadius:[0,4,4,0]}},
   {name:'完成',type:'bar',data:o.d.slice().reverse(),barWidth:'32%',
    itemStyle:{color:AC,borderRadius:[0,4,4,0]}}]}),true);
}
draw4(0);
document.getElementById('tabs').addEventListener('click',function(e){
 var t=e.target.closest('.tab');if(!t)return;
 [].forEach.call(this.children,function(x){x.classList.remove('on')});
 t.classList.add('on');draw4(+t.dataset.k);});
window.addEventListener('resize',function(){
 ['c1','c2','c3','c4'].forEach(function(id){
  var ins=echarts.getInstanceByDom(document.getElementById(id));if(ins)ins.resize();});});
"""


def render_html(days, daily, weekly, total, prog, notes):
    inc = []
    for i in range(6):
        row = []
        for d in days:
            s = 0.0
            for n in TARGETS:
                v = daily[d].get(n)
                if v:
                    s += v[i]
            row.append(round(s, 2))
        inc.append(row)
    p4 = []
    for i in range(5):
        p4.append({'n': '%s（%s）' % (METRICS[i], UNITS[i]),
                   't': [weekly[n]['target'][i] for n in TARGETS],
                   'd': [weekly[n]['done'][i] for n in TARGETS]})
    js = (JS.replace('__METRICS__', json.dumps(METRICS, ensure_ascii=False))
            .replace('__DAYS__', json.dumps([d[5:] for d in days], ensure_ascii=False))
            .replace('__RATE__', json.dumps(total['rate']))
            .replace('__PROG__', str(prog))
            .replace('__T2__', json.dumps([round(v, 2) for v in total['target']]))
            .replace('__D2__', json.dumps([round(v, 2) for v in total['done']]))
            .replace('__INC__', json.dumps(inc))
            .replace('__PPL__', json.dumps(TARGETS, ensure_ascii=False))
            .replace('__P4__', json.dumps(p4, ensure_ascii=False))
            .replace('SERIESNAME', json.dumps(
                ['%s(%s)' % (SERIES[i], UNITS[i]) for i in range(6)], ensure_ascii=False)))
    note = '<br>\n'.join(notes) if notes else '无'
    tabs = ''.join('<div class="tab%s" data-k="%d">%s（%s）</div>' %
                   (' on' if i == 0 else '', i, METRICS[i], UNITS[i])
                   for i in range(5))
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>滨康大区经理日报 · 图表版 __RANGE__</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>__CSS__</style></head><body><div class="wrap">
<h1>滨康大区经理日报 · 图表版</h1>
<div class="sub">统计周期：__RANGE__　·　应报 __N__ 人</div>
<div class="meta">数据源：钉钉日志接口（滨康新日报表）　·　生成时间：__NOW__</div>
<div id="err">图表库加载失败。当前环境可能无法访问 CDN，请联网后刷新，或改用表格版本。</div>
<section><h2>一、本周达成率</h2>
<p class="desc">柱状图 + 时间进度基准线。柱高为达成率，虚线为 __PROG__% 时间进度；高于基准为领先，低于为滞后。</p>
<div class="card"><div id="c1" class="chart"></div></div></section>
<section><h2>二、目标与实际完成</h2>
<p class="desc">分组柱状图。发货单位为万元（左侧独立坐标区），其余为个数（右侧坐标区）；两者量纲不同，分轴展示。</p>
<div class="card"><div id="c2" class="chart" style="height:360px"></div></div></section>
<section><h2>三、当日增量走势</h2>
<p class="desc">折线图。反映每日新增变化；出现负值即表示累计回退，属填报异常。</p>
<div class="card"><div id="c3" class="chart" style="height:360px"></div></div></section>
<section><h2>四、各人目标与完成</h2>
<p class="desc">横向条形图。点击切换指标，默认显示发货（万元）。</p>
<div class="tabs" id="tabs">__TABS__</div>
<div class="card"><div id="c4" class="chart" style="height:420px"></div></div></section>
<div class="note"><b>数据异常</b><br>__NOTE__</div>
<footer>计算规则：日增量 = 当日累计 − 前一日累计（首日即累计值）；周累计取本周最后一次填报值；
目标取本周首次填报值；未提交与零目标均计入分母。<br>
群消息推送文本缺失回访、自媒体、拜访零售店三项字段，统计以日志接口为准。</footer>
</div>
<script>if(typeof echarts==='undefined'){document.getElementById('err').style.display='block';}
else{__JS__}</script>
</body></html>""".replace('__CSS__', CSS).replace('__JS__', js) \
        .replace('__RANGE__', '%s ~ %s' % (days[0], days[-1])) \
        .replace('__N__', str(len(TARGETS))).replace('__TABS__', tabs) \
        .replace('__NOTE__', note).replace('__PROG__', str(prog)) \
        .replace('__NOW__', dt.datetime.now().strftime('%Y-%m-%d %H:%M'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--out', default='')
    ap.add_argument('--format', default='html', choices=['html', 'table', 'json'])
    ap.add_argument('--progress', type=int, default=0,
                    help='时间进度百分比，默认按已过天数/7 计算')
    a = ap.parse_args()

    days = day_range(a.start, a.end)
    data = collect(days)
    daily, weekly, total = compute(data, days)
    notes = anomalies(data, daily, days)
    prog = a.progress or round(len(days) / 7 * 100)

    print('\n[summary] 周期 %s ~ %s，共 %d 天' % (days[0], days[-1], len(days)))
    for i in range(5):
        print('  %s：目标 %s，完成 %s，达成 %d%%' %
              (METRICS[i], fmt(total['target'][i]), fmt(total['done'][i]), total['rate'][i]))
    print('  时间进度 %d%%' % prog)
    if notes:
        print('\n[anomalies]')
        for x in notes:
            print('  - ' + x)

    if a.format == 'table':
        print('\n' + render_table(daily, weekly, total, days))
    elif a.format == 'json':
        print(json.dumps({'days': days, 'daily': daily, 'weekly': weekly,
                          'total': total, 'anomalies': notes},
                         ensure_ascii=False, indent=2))
    else:
        out = a.out or ('binkang_report_%s.html' % days[-1].replace('-', ''))
        with open(out, 'w', encoding='utf-8') as f:
            f.write(render_html(days, daily, weekly, total, prog, notes))
        print('\n[out] %s' % out)


if __name__ == '__main__':
    main()
