"""Render the proposed telephone-booking sequence with explicit human consent.

SVG is the readable diagram source; PNG is used for the Word/PDF export.
Dashed lines are replies. This is a business collaboration view, not API code.
"""
from pathlib import Path
import argparse
from html import escape
from PIL import Image,ImageDraw,ImageFont

def draw(output,font_file):
    width,height=2000,1370
    im=Image.new('RGB',(width,height),'white');pen=ImageDraw.Draw(im)
    font=ImageFont.truetype(str(font_file),36)
    title=ImageFont.truetype(str(font_file),42)
    small=ImageFont.truetype(str(font_file),30)
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
         '<rect width="100%" height="100%" fill="white"/>',
         '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L8,5 L0,10" fill="none" stroke="black" stroke-width="1.3"/></marker></defs>']
    def text(x,y,s,size=36):
        pen.text((x,y),s,anchor='mm',font={42:title,30:small}.get(size,font),fill='black')
        svg.append(f'<text x="{x}" y="{y}" text-anchor="middle" dominant-baseline="central" font-family="Noto Sans CJK SC" font-size="{size}">{escape(s)}</text>')
    def line(x1,y1,x2,y2,dash=False,arrow=False):
        if dash:
            import math
            length=math.hypot(x2-x1,y2-y1)
            for s in range(0,int(length),22):
                e=min(s+12,length)
                pen.line((x1+(x2-x1)*s/length,y1+(y2-y1)*s/length,x1+(x2-x1)*e/length,y1+(y2-y1)*e/length),fill='black',width=3)
        else:pen.line((x1,y1,x2,y2),fill='black',width=3)
        if arrow:
            sign=1 if x2>x1 else -1
            pen.line((x2-sign*18,y2-10,x2,y2,x2-sign*18,y2+10),fill='black',width=3)
        svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="black" stroke-width="3"'+(' stroke-dasharray="12 10"' if dash else '')+(' marker-end="url(#arrow)"' if arrow else '')+'/>')
    actors=[(170,'患者'),(900,'前台'),(1770,'预约系统')]
    for x,label in actors:
        pen.rectangle((x-120,35,x+120,115),outline='black',width=3)
        svg.append(f'<rect x="{x-120}" y="35" width="240" height="80" fill="white" stroke="black" stroke-width="3"/>')
        text(x,75,label,42);line(x,115,x,1280,dash=True)
    def message(a,b,y,label,reply=False):
        line(a,y,b,y,dash=reply,arrow=True);text((a+b)/2,y-38,label)
    message(170,900,215,'1 来电：诉求、日期与联络信息')
    message(900,1770,345,'2 核对患者档案与可用安排')
    message(1770,900,475,'3 返回候选及待人工核对条件',True)
    message(900,170,605,'4 解释医师、时间和资源方案')
    message(170,900,735,'5 明确接受／另选／暂缓',True)
    text(1000,805,'未明确同意：记录待联系或未成约；不生成预约、不占用',30)
    message(900,1770,905,'6 患者同意后提交最终确认')
    # Self-call: current authorization and resources must still be valid.
    line(1770,965,1930,965);line(1930,965,1930,1025);line(1930,1025,1770,1025,arrow=True)
    text(1330,978,'7 重验授权与占用',30);text(1330,1020,'保存唯一预约',30)
    message(1770,900,1145,'8 返回编号；冲突则重新协商',True)
    message(900,170,1275,'9 交付安排及查询、取消改期方式',True)
    text(1000,1335,'目标业务序列：新增接待单与资源联动的实现状态见正文',30)
    svg.append('</svg>')
    output.parent.mkdir(parents=True,exist_ok=True)
    im.save(output)
    output.with_suffix('.svg').write_text('\n'.join(svg)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--font-file',type=Path,required=True)
    a=p.parse_args();draw(a.output,a.font_file)
