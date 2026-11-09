const api = require('../../utils/api');
const navigation = require('../../utils/navigation');
const {dateTime, showError} = require('../../utils/format');

Page({
  data: {statement: null, busy: false, error: '', requestId: ''},
  onShow() { return this.load(this.clinic, this.page); },
  onHide() {
    this.requestSequence = (this.requestSequence || 0) + 1;
    this.setData({statement: null});
  },
  async load(clinic = '', page = 1) {
    const sequence = (this.requestSequence || 0) + 1;
    this.requestSequence = sequence;
    this.setData({statement: null, busy: true, error: '', requestId: ''});
    try {
      const statement = await api.request('funds/', 'GET', {clinic, page});
      if (sequence !== this.requestSequence) return;
      statement.entries = statement.entries.map(row => ({...row, postedLabel: dateTime(row.posted_at)}));
      this.clinic = statement.selected ? statement.selected.id : '';
      this.page = statement.page;
      this.setData({statement, busy: false});
    } catch (error) {
      if (sequence === this.requestSequence) showError(this, error, {separateRequestId: true});
    }
  },
  selectClinic(event) {
    if (!this.data.busy) return this.load(event.currentTarget.dataset.clinic);
  },
  turn(event) {
    const {statement, busy} = this.data;
    if (busy || !statement) return;
    const page = statement[event.currentTarget.dataset.direction];
    if (page) return this.load(this.clinic, page);
  },
  retry() { return this.load(); },
  back() { navigation.returnTo('/pages/home/index'); }
});
