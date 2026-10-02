import { scenarioForSelection } from "./scenario";
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DecisionDeskApp } from './DecisionDeskApp';
import fixtures from './preview-fixtures.json';
import { discoverDesk, compareDesk, reviewObservation, PREVIEW_SCENARIOS } from './preview';
import { validateDecisionDesk, validateDeskComparison } from './client';
import { DEFAULT_DESK_CRITERIA } from './types';
import { appendObservationReview, loadObserveState, saveObservation, emptyObserveState, OBSERVE_STORAGE_KEY } from './observeStore';

beforeEach(() => { localStorage.clear(); vi.spyOn(window, 'scrollTo').mockImplementation(() => {}); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('private cloud replay boundary', () => {
  it('retains all original identities and validates every original Python output', () => {
    expect(fixtures.synthetic).toBe(true);
    for (const fixture of Object.values(fixtures.assets)) {
      const desk = validateDecisionDesk(fixture.desk);
      expect(desk.source.provider).toBe('SYNTHETIC_DEMO');
      expect(desk.qualification.execution_allowed).toBe(false);
      expect(fixture.selected_ids).toHaveLength(3);
      expect(fixture.comparisons).toHaveLength(16);
      for (const result of fixture.comparisons) {
        expect(validateDeskComparison(result)).toEqual(result);
        expect(result.analysis_id).toBe(desk.analysis_id);
        expect(result.snapshot_id).toBe(desk.snapshot_id);
      }
    }
  });
  it('rejects live mode, arbitrary filters, identities, legs and scenarios', async () => {
    await expect(discoverDesk('BTC', DEFAULT_DESK_CRITERIA, 'live')).rejects.toThrow();
    await expect(discoverDesk('BTC', {...DEFAULT_DESK_CRITERIA, dte_min:1}, 'demo')).rejects.toThrow();
    const f = fixtures.assets.BTC;
    await expect(compareDesk(f.desk.snapshot_id, f.selected_ids, {...PREVIEW_SCENARIOS[0].value, price_change_pct:1}, f.desk.analysis_id)).rejects.toThrow();
    await expect(compareDesk(f.desk.snapshot_id, f.selected_ids, PREVIEW_SCENARIOS[0].value, 'wrong-analysis')).rejects.toThrow();
    await expect(compareDesk(f.desk.snapshot_id, [f.selected_ids[0], f.selected_ids[0]], PREVIEW_SCENARIOS[0].value, f.desk.analysis_id)).rejects.toThrow();
  });
  it('resets to a supported tuple after a preset, reset, asset switch or empty selection', async () => {
    const desk=await discoverDesk('BTC',DEFAULT_DESK_CRITERIA,'demo');
    const changed=PREVIEW_SCENARIOS[2].value;
    expect(scenarioForSelection(null,[],changed)).toEqual(PREVIEW_SCENARIOS[0].value);
    expect(scenarioForSelection(desk,[],changed)).toEqual(PREVIEW_SCENARIOS[0].value);
    expect(scenarioForSelection(desk,[desk.candidates[0]],{...changed,time_days:0})).toEqual(PREVIEW_SCENARIOS[0].value);
    const view=render(<DecisionDeskApp />);
    await waitFor(() => expect(screen.getAllByRole('button',{name:'加入比较'})).toHaveLength(3));
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getByRole('button',{name:/比较这些结构/}));
    await screen.findByRole('heading',{name:'条件到期损益'});
    fireEvent.click(screen.getByRole('button',{name:'下跌 10% · IV +10'}));
    fireEvent.click(screen.getByRole('button',{name:'ETH',exact:true}));
    await waitFor(() => expect(screen.getAllByRole('button',{name:'加入比较'})).toHaveLength(3));
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getByRole('button',{name:/比较这些结构/}));
    await screen.findByRole('heading',{name:'条件到期损益'});
    expect(screen.getByRole('button',{name:'原始假设'})).toHaveAttribute('aria-pressed','true');
    view.unmount();
  });
  it('returns unavailable for review and never pretends to obtain new quotes', async () => {
    const desk=await discoverDesk('BTC',DEFAULT_DESK_CRITERIA,'demo');
    const response=await reviewObservation({desk,candidate_id:desk.candidates[0].candidate_id});
    expect(response.status).toBe('unavailable'); expect(response.desk).toBe(null);
    expect(response.reasons[0].code).toBe('CLOUD_PREVIEW_NO_LIVE_BACKEND');
  });
  it('allows discovery, exact preset comparison, save, reload and honest review without fetch', async () => {
    const network=vi.spyOn(globalThis,'fetch').mockRejectedValue(new Error('Network forbidden'));
    const view=render(<DecisionDeskApp />);
    await waitFor(() => expect(screen.getAllByRole('button',{name:'加入比较'})).toHaveLength(3));
    expect(screen.getByRole('button',{name:'实时行情未接入'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'应用筛选'})).toBeDisabled();
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getByRole('button',{name:/比较这些结构/}));
    await screen.findByRole('heading',{name:'条件到期损益'});
    fireEvent.click(screen.getByRole('button',{name:'下跌 10% · IV +10'}));
    fireEvent.click(screen.getByRole('button',{name:'载入预计算比较'}));
    await screen.findByRole('heading',{name:'条件到期损益'});
    fireEvent.click(screen.getAllByRole('radio')[0]);
    fireEvent.click(screen.getByRole('button',{name:'保存到本地观察'}));
    await screen.findByRole('heading',{name:'保留样例判断，体验观察记录'});
    expect(loadObserveState().state.records).toHaveLength(1);
    expect(JSON.parse(localStorage.getItem(OBSERVE_STORAGE_KEY)!).records[0].comparison.scenario.price_change_pct).toBe(-10);
    view.unmount(); render(<DecisionDeskApp />);
    fireEvent.click(screen.getByRole('button',{name:/03.*观察复盘/}));
    await screen.findByRole('button',{name:'查看复核限制'});
    fireEvent.click(screen.getByRole('button',{name:'查看复核限制'}));
    await screen.findAllByText(/此页面只有固定合成回放/);
    expect(loadObserveState().state.reviews[0].review?.status).toBe('unavailable');
    expect(network).not.toHaveBeenCalled();
  });
  it('keeps a loaded comparison when the active preset is clicked again', async () => {
    const loadComparison=vi.fn(compareDesk);
    render(<DecisionDeskApp loadComparison={loadComparison} />);
    await waitFor(() => expect(screen.getAllByRole('button',{name:'加入比较'})).toHaveLength(3));
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getByRole('button',{name:/比较这些结构/}));
    await screen.findByRole('heading',{name:'条件到期损益'});
    fireEvent.click(screen.getAllByRole('radio')[0]);
    fireEvent.click(screen.getByRole('button',{name:'原始假设'}));
    expect(screen.getByRole('heading',{name:'条件到期损益'})).toBeVisible();
    expect(screen.getByRole('button',{name:'保存到本地观察'})).toBeEnabled();
    expect(loadComparison).toHaveBeenCalledTimes(1);
  });
  it('reports the count of the displayed sample structure filter', async () => {
    render(<DecisionDeskApp />);
    await screen.findByRole('heading',{name:'从完整结构开始比较'});
    fireEvent.change(screen.getByRole('combobox',{name:'结构'}),{target:{value:'IRON_CONDOR'}});
    expect(screen.getAllByRole('button',{name:'加入比较'})).toHaveLength(1);
    expect(screen.getByText(/1 个样例在回放时刻可比较/)).toBeVisible();
  });
  it('keeps the comparison and offers manual copy when browser storage fails', async () => {
    render(<DecisionDeskApp />);
    await waitFor(() => expect(screen.getAllByRole('button',{name:'加入比较'})).toHaveLength(3));
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getAllByRole('button',{name:'加入比较'})[0]);
    fireEvent.click(screen.getByRole('button',{name:/比较这些结构/}));
    await screen.findByRole('heading',{name:'条件到期损益'});
    fireEvent.click(screen.getAllByRole('radio')[0]);
    vi.spyOn(Storage.prototype,'setItem').mockImplementation(() => { throw new Error('quota'); });
    fireEvent.click(screen.getByRole('button',{name:'保存到本地观察'}));
    expect(screen.getByRole('alert')).toHaveTextContent('观察记录未保存');
    expect(screen.getByRole('heading',{name:'条件到期损益'})).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:'复制研究复核'}));
    const copy=await screen.findByRole('textbox',{name:'研究复核文本'});
    expect((copy as HTMLTextAreaElement).value).toContain('SYNTHETIC FROZEN REPLAY / NOT LIVE');
    expect(loadObserveState().state.records).toHaveLength(0);
  });
  it('never promotes local synthetic observations into live or current market evidence', async () => {
    const desk=await discoverDesk('BTC',DEFAULT_DESK_CRITERIA,'demo');
    const saved=saveObservation(emptyObserveState(),{desk,candidate_id:desk.candidates[0].candidate_id,
      comparison:null,viewpoint:'all',note:'原始样例'});
    const original=localStorage.getItem(OBSERVE_STORAGE_KEY);
    const review=await reviewObservation(saved.record);
    expect(() => appendObservationReview(saved.state,saved.record.id,{...review,status:'current',desk,
      reviewed_candidate_id:saved.record.candidate_id})).toThrow();
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBe(original);
    const altered=JSON.parse(original!);
    altered.records[0].desk.source.mode='live';
    localStorage.setItem(OBSERVE_STORAGE_KEY,JSON.stringify(altered));
    expect(loadObserveState().error).not.toBeNull();
    expect(loadObserveState().state.records).toHaveLength(0);
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBe(JSON.stringify(altered));
  });

});
