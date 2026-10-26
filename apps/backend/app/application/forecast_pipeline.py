"""Real first-week Forecast collection with remote model scoring."""
import asyncio
import hashlib

from ..adapters.analysis_rpc import AnalysisRpc
from ..adapters.etherscan_client import BackendEtherscan
from ..adapters.remote_predictor import ForecastRemotePredictor, outcome_cache_kind
from ..api.schemas import AnalysisRequest, AnalysisResult
from ..errors import ServiceError
from .forecast_collection import ForecastCollection
from .forecast_inputs import ForecastWindow, prepare_input
from .forecast_presentation import ForecastDisplay


class ForecastPipeline:
    def __init__(self,settings,store,budget,*,rpc=None,etherscan=None,predictor=None):
        self.settings,self.store,self.budget = settings,store,budget
        self.rpc = rpc or AnalysisRpc(settings)
        self.etherscan = etherscan or BackendEtherscan(settings,budget)
        self.predictor = predictor or ForecastRemotePredictor(settings)

    async def close(self):
        await self.rpc.close(); await self.etherscan.close(); await self.predictor.close()

    async def execute(self,lease):
        request = AnalysisRequest.model_validate(lease['command'])
        collector = ForecastCollection(self.store,lease,self.settings,self.etherscan,self.rpc)
        collector.stage('resolving','Resolving token, selected pools and the first-seven-day observation window')
        context = await collector.freeze(request)
        outcome = {'task_id':'continued_activity','status':'pending','score':None}
        payload = None
        if not context['pools']:
            outcome.update(status='not_applicable',reason_code='unsupported_pool',
                reason='No supported Ethereum Uniswap v2 pool was found to establish the first-seven-day observation window.')
        else:
            if not context['observation_complete']:
                outcome.update(status='insufficient_history',reason_code='observation_not_mature',
                    reason='The selected pool has not completed its first seven days. A Forecast score is unavailable until that window closes.')
            self.store.save(lease,{'tasks':[outcome]})
            collector.stage('collecting','Collecting all token and selected-pool logs in the first seven days')
            selection = await ForecastWindow(collector).collect(context)
            views = ForecastDisplay.restore(context,selection).views()
            self.store.save(lease,{'graphs':views})
            collector.stage('normalizing','Reconciling first-week swap sender identities and pool event units')
            _,total = self.store.transactions(lease['id'],'pool_event',0,0)
            ledger,_ = self.store.transactions(lease['id'],'pool_event',total,0)
            sample_id = hashlib.sha256(f"{lease['id']}:{context['snapshot_id']}:forecast-input-1".encode()).hexdigest()
            payload,quality = await asyncio.to_thread(prepare_input,context,ledger,sample_id)
            self.store.save(lease,{},artifacts={('forecast_input_quality',''):quality})
            collector.stage('building_graph','Building the first-week wallet-pool-token model input')
            if payload:
                graph = payload['graph_sample']
                views['continued_activity']['context'].update(model_sample_id=sample_id,
                    model_nodes=len(graph['node_refs']),model_edges=len(graph['edge_index'][0]))
                self.store.save(lease,{'graphs':views},artifacts={('graph_sample','continued_activity'):graph})
            if context['observation_complete']:
                if not payload:
                    outcome.update(status='data_incomplete',reason_code='forecast_input_invalid',
                        reason='The first-week swap participant data could not satisfy the Forecast input contract.')
                elif not payload['graph_sample']['stats']['window_swap_count']:
                    outcome.update(status='no_activity',reason_code='no_activity',
                        reason='No swap activity was found in the selected pools during the first seven days. No score was generated.')
                else:
                    collector.stage('predicting','Requesting the Forecast model score and label')
                    cache_kind = outcome_cache_kind('continued_activity')
                    cached = self.store.artifact(lease['id'],cache_kind,'continued_activity')
                    if cached:
                        if cached['sample_id'] != sample_id:
                            raise ServiceError('data_incomplete')
                        outcome = cached
                    else:
                        outcome,delivery = await self.predictor.predict(payload,collector.directory)
                        self.store.save(lease,{'tasks':[outcome]},artifacts={(cache_kind,'continued_activity'):outcome,
                            ('model_delivery','continued_activity'):delivery})
            header = await self.rpc.call('eth_getBlockByNumber',[hex(context['cutoff_block']),False])
            if not isinstance(header,dict) or header.get('hash') != context['cutoff_hash']:
                raise ServiceError('data_incomplete')
        complete = outcome['status'] == 'ok'
        result = self.store.get(lease['id'])
        result.update(status='completed' if complete else 'partial',stage='completed',tasks=[outcome],
            message='First-week activity is ready.' if complete else outcome.get('reason'),
            progress={'state':'completed' if complete else 'partial','unit':'tasks','completed':1,'total':1,'total_final':True})
        AnalysisResult.model_validate(result)
        self.store.save(lease,result,finish=True)
