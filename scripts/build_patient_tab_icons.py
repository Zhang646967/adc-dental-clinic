"""Render the four original line icons required by native WeChat tabBar."""
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]/'clients/wechat/miniprogram/assets/tabs'


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    for name in ['home','booking','visits','account']:
        for suffix,color in [('', '#667a72'),('-active','#14685d')]:
            image=Image.new('RGBA',(64,64),(0,0,0,0));d=ImageDraw.Draw(image)
            if name=='home':
                d.line([(8,29),(32,9),(56,29)],fill=color,width=4,joint='curve')
                d.line([(15,27),(15,55),(49,55),(49,27)],fill=color,width=4)
                d.line([(27,55),(27,38),(37,38),(37,55)],fill=color,width=4)
            elif name=='booking':
                d.rounded_rectangle((10,15,54,55),radius=7,outline=color,width=4)
                d.line((11,27,53,27),fill=color,width=4)
                for x in [22,42]:d.line((x,8,x,21),fill=color,width=4)
                for x,y in [(22,36),(34,36),(22,46),(34,46),(46,36)]:d.ellipse((x-2,y-2,x+2,y+2),fill=color)
            elif name=='visits':
                d.rounded_rectangle((14,13,50,57),radius=6,outline=color,width=4)
                d.rounded_rectangle((24,7,40,19),radius=3,fill=color)
                for y in [29,40,50]:d.line((24,y,41,y),fill=color,width=3)
            else:
                d.ellipse((23,8,41,27),outline=color,width=4)
                d.arc((12,31,52,69),180,360,fill=color,width=4)
                d.line((12,50,12,55,52,55,52,50),fill=color,width=4)
            image.save(ROOT/(name+suffix+'.png'))


if __name__=='__main__':main()
