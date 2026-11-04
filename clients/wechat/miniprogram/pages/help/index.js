const api=require('../../utils/api');
const {arrangement,showError}=require('../../utils/format');
Page({
  data:{clinics:[],error:'',environmentLabel:'',focus:null,focusClinicId:null},
  async onLoad(q){
    const n=Number(q&&q.visit);
    this.visitId=Number.isSafeInteger(n)&&n>0?n:null;
    api.showSubject(this);
    try{
      const session=await api.bootstrap();api.showSubject(this);
      this.setData({environmentLabel:session.environment_label||''});
      if(!session.authenticated)return;
      let focus=null;
      if(this.visitId){
        try{focus=arrangement(await api.request(`visits/${this.visitId}/`));}catch(e){focus=null;}
      }
      const clinics=(await api.request('catalogue/')).clinics||[];
      const focusClinicId=focus?focus.clinic_id:null;
      // Put the clinic of the appointment the patient came from first.
      const ordered=focusClinicId?clinics.slice().sort((a,b)=>(b.id===focusClinicId?1:0)-(a.id===focusClinicId?1:0)):clinics;
      this.setData({clinics:ordered,focusClinicId,focus:focus?{id:focus.id,clinic:focus.clinic,startLabel:focus.startLabel,status_label:focus.status_label,needs_outcome_review:!!focus.needs_outcome_review}:null});
    }catch(e){showError(this,e);}
  }
});
