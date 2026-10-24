// Original bounded CFR+ numeric traversal. No poker rules or hand evaluation here.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <vector>

namespace {
struct Solver {
    int players,nodes,deals,infos,root;
    const int32_t *actors,*edges_at,*edges,*info,*terminal,*owners,*actions_at;
    const double *utility,*chance;
    std::vector<double> regret,average,policy,delta,values;
    std::array<double,6> reach;
    int target,deal,iteration;
    double visit(int node) {
        int actor=actors[node];
        if(actor==-1) return utility[(static_cast<size_t>(terminal[node])*deals+deal)*players+target];
        int key=info[static_cast<size_t>(deal)*nodes+node],start=actions_at[key];
        int first=edges_at[node],count=edges_at[node+1]-first;
        double saved=reach[actor];
        for(int a=0;a<count;++a) {
            reach[actor]=saved*policy[start+a];
            values[first+a]=visit(edges[first+a]);
        }
        reach[actor]=saved;
        double value=0.;
        for(int a=0;a<count;++a)value+=policy[start+a]*values[first+a];
        if(actor==target) {
            double others=1.;
            for(int p=0;p<players;++p)if(p!=actor)others*=reach[p];
            double cf=chance[deal]*others;
            for(int a=0;a<count;++a) {
                delta[start+a]+=cf*(values[first+a]-value);
                average[start+a]+=iteration*chance[deal]*saved*policy[start+a];
            }
        }
        return value;
    }
};
}
extern "C" int poker_cfr_abi(){return 1;}
extern "C" int poker_cfr_train(int players,int nodes,int deals,int infos,int terminals,int root,int iterations,
    const int32_t *actors,const int32_t *edges_at,const int32_t *edges,const int32_t *info,
    const int32_t *terminal,const double *utility,const double *chance,const int32_t *owners,
    const int32_t *actions_at,double *output) {
    if(players<2||players>6||nodes<1||nodes>20000||deals<1||deals>4096||infos<0||terminals<1||
       root<0||root>=nodes||iterations<1||iterations>2000||static_cast<int64_t>(nodes)*deals>1000000)return 1;
    // The Python wrapper owns buffer lengths. Validate graph/indices before recursion.
    if(edges_at[0]!=0||actions_at[0]!=0)return 2;
    try {
    std::vector<int> parents(nodes,0);
    for(int n=0;n<nodes;++n) {
        int count=edges_at[n+1]-edges_at[n];
        if(count<0||count>6||actors[n]<-1||actors[n]>=players)return 2;
        if(actors[n]==-1) {if(count||terminal[n]<0||terminal[n]>=terminals)return 2;}
        else if(!count)return 2;
        for(int a=edges_at[n];a<edges_at[n+1];++a) {
            if(edges[a]<0||edges[a]>=n||++parents[edges[a]]!=1)return 2; // postorder tree
        }
    }
    for(int n=0;n<nodes;++n)if(parents[n]!=(n==root?0:1))return 2;
    for(int k=0;k<infos;++k)if(owners[k]<0||owners[k]>=players||actions_at[k+1]<=actions_at[k]||actions_at[k+1]-actions_at[k]>6)return 2;
    for(int d=0;d<deals;++d) {
        if(!std::isfinite(chance[d])||chance[d]<=0)return 2;
        for(int n=0;n<nodes;++n)if(actors[n]!=-1) {
            int k=info[static_cast<size_t>(d)*nodes+n];
            if(k<0||k>=infos||owners[k]!=actors[n]||actions_at[k+1]-actions_at[k]!=edges_at[n+1]-edges_at[n])return 2;
        }
    }
    for(size_t i=0;i<static_cast<size_t>(terminals)*deals*players;++i)if(!std::isfinite(utility[i]))return 2;
        Solver s{players,nodes,deals,infos,root,actors,edges_at,edges,info,terminal,owners,actions_at,utility,chance,
                 std::vector<double>(actions_at[infos],0.),std::vector<double>(actions_at[infos],0.),
                 std::vector<double>(actions_at[infos],0.),std::vector<double>(actions_at[infos],0.),
                 std::vector<double>(edges_at[nodes],0.),{},0,0,0};
        for(int k=0;k<infos;++k)for(int a=actions_at[k];a<actions_at[k+1];++a)s.policy[a]=1./(actions_at[k+1]-actions_at[k]);
        for(s.iteration=1;s.iteration<=iterations;++s.iteration)for(s.target=0;s.target<players;++s.target) {
            bool acts=false;for(int k=0;k<infos;++k)if(owners[k]==s.target){acts=true;break;}
            if(!acts)continue;
            std::fill(s.delta.begin(),s.delta.end(),0.);
            for(s.deal=0;s.deal<deals;++s.deal){s.reach.fill(1.);s.visit(root);}
            for(int k=0;k<infos;++k)if(owners[k]==s.target) {
                double total=0.;
                for(int a=actions_at[k];a<actions_at[k+1];++a){s.regret[a]=std::max(0.,s.regret[a]+s.delta[a]);total+=s.regret[a];}
                for(int a=actions_at[k];a<actions_at[k+1];++a)s.policy[a]=total>0?s.regret[a]/total:1./(actions_at[k+1]-actions_at[k]);
            }
        }
        for(int k=0;k<infos;++k) {
            double total=0.;for(int a=actions_at[k];a<actions_at[k+1];++a)total+=s.average[a];
            for(int a=actions_at[k];a<actions_at[k+1];++a)output[a]=total>0?s.average[a]/total:1./(actions_at[k+1]-actions_at[k]);
        }
        return 0;
    }catch(...){return 3;}
}
