"""Render a responsibility view, not a claim of business automation."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import argparse

def draw(output,font_file):
 im=Image.new('RGB',(1800,1320),'white');d=ImageDraw.Draw(im)
 title=ImageFont.truetype(str(font_file),42);body=ImageFont.truetype(str(font_file),34);small=ImageFont.truetype(str(font_file),29)
 def box(rect,lines):
  d.rectangle(rect,fill='#f6f6f6',outline='#333333',width=3)
  x1,y1,x2,y2=rect
  for i,line in enumerate(lines):d.text(((x1+x2)/2,y1+32+55*i),line,font=title if i==0 else body,anchor='mt',fill='black')
 def arrow(points,label=None,at=None):
  d.line(points,fill='#333333',width=4)
  (x0,y0),(x1,y1)=points[-2:]
  if y1>y0:head=[(x1-11,y1-17),(x1,y1),(x1+11,y1-17)]
  elif y1<y0:head=[(x1-11,y1+17),(x1,y1),(x1+11,y1+17)]
  elif x1>x0:head=[(x1-17,y1-11),(x1,y1),(x1-17,y1+11)]
  else:head=[(x1+17,y1-11),(x1,y1),(x1+17,y1+11)]
  d.line(head,fill='#333333',width=4)
  if label:d.text(at,label,font=small,anchor='mm',fill='black')
 box((80,55,810,275),['业务操作 Business command','任务＋审计＋发件箱','同一事务保留原业务保证'])
 box((990,55,1720,275),['通知 Worker','短事务锁定已提交事件','消息＋派发状态一起提交'])
 arrow([(810,165),(990,165)],'意图',(900,120))
 box((80,385,810,605),['业务数据库 Database','只读计数与到期时间','不读取收件人或任务正文'])
 box((990,385,1720,605),['心跳 Heartbeat','观测／DB成功／非空投递','成功时间在业务提交后更新'])
 arrow([(1355,275),(1355,385)],'仅写心跳',(1480,330))
 box((80,745,810,965),['独立 Collector','每30秒采样与条件计算','不重试通知或修复业务'])
 arrow([(445,605),(445,745)],'只读聚合',(560,675))
 arrow([(1170,605),(1170,675),(700,675),(700,745)])
 box((990,745,1720,965),['私有 Monitor state','条件＋事件生命周期','原子替换／有界保留'])
 arrow([(810,855),(990,855)],'仅写状态',(900,810))
 box((390,1080,1410,1260),['独立 Reader 与维护责任人','无需数据库也能识别观测过期','确认责任 ≠ 清除故障 ≠ 重新办理业务'])
 arrow([(1355,965),(1355,1080)],'读取',(1450,1020))
 im.save(output)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--font-file',type=Path,required=True);a=p.parse_args();draw(a.output,a.font_file)
