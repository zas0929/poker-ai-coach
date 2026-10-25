// Exact factored turn CFR+. Separate ABI; the frozen river kernel is unchanged.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>
struct TurnInput {
 int32_t p,n,d,r,k,t,root,slots,button,edge_count;
 const int32_t *actor,*at,*child,*street,*mask,*prune,*paid,*base,*hands,*own,*river,*rank,*ranks,*term,*state_paid,*state_mask,*initial;
 const double *chance;
 int32_t *utility;
};
namespace {
struct Budget {};
bool valid(const TurnInput &g) {
 if(g.p<2||g.p>6||g.n<1||g.n>30000||g.d<1||g.d>4096||g.r<1||g.r>48||g.k<1||g.k>4096||g.t<1||g.t>g.n||
    g.root<0||g.root>=g.n||g.slots<0||g.slots>6000000||g.button<0||g.button>=g.p||
    g.edge_count!=g.n-1||int64_t(g.t)*g.k*g.p+g.slots>6000000) return false;
 if(g.at[0]||g.at[g.n]!=g.edge_count) return false;
 std::vector<int> parents(g.n,0),depth(g.n,1);int expected_base=0;
 for(int p=0;p<g.p;++p) if(g.hands[p]<1||g.hands[p]>4096||g.initial[p]<0) return false;
 for(int n=0;n<g.n;++n) {
  int a=g.actor[n],count=g.at[n+1]-g.at[n];
  if(a< -2||a>=g.p||count<0||count>6||g.mask[n]<1||g.mask[n]>=(1<<g.p)||g.prune[n]<0||g.prune[n]>=(1<<g.p)||(g.prune[n]&g.mask[n]))return false;
  if(a==-1) { if(count||g.term[n]<0||g.term[n]>=g.t)return false; }
  else if(a==-2) {if(count!=1)return false;}
  else {
   if(count<1||g.street[n]<0||g.street[n]>1||!(g.mask[n]&(1<<a)))return false;
   int64_t cells=int64_t(count)*g.hands[a]*(g.street[n]?g.r:1);
   if(count>1) {
    if(g.base[n]!=expected_base||g.base[n]+cells>g.slots)return false;
    expected_base+=cells;
   } else if(g.base[n]!=-1)return false;
  }
  for(int p=0;p<g.p;++p) {
   if(g.paid[n*g.p+p]<0||g.paid[n*g.p+p]>10000)return false;
   if(a==-1&&(g.paid[n*g.p+p]!=g.state_paid[g.term[n]*g.p+p]||g.mask[n]!=g.state_mask[g.term[n]]))return false;
  }
  for(int j=g.at[n];j<g.at[n+1];++j) {
   int c=g.child[j];if(c<0||c>=n||++parents[c]!=1)return false;
   depth[n]=std::max(depth[n],1+depth[c]);if(depth[n]>128)return false;
  }
 }
 if(expected_base!=g.slots)return false;
 for(int t=0;t<g.t;++t) {
  if(g.state_mask[t]<1||g.state_mask[t]>=(1<<g.p))return false;
  for(int p=0;p<g.p;++p)if(g.state_paid[t*g.p+p]<0||g.state_paid[t*g.p+p]>10000)return false;
 }
 for(int n=0;n<g.n;++n)if(parents[n]!=(n==g.root?0:1))return false;
 double total=0;
 for(int d=0;d<g.d;++d) {
  if(!std::isfinite(g.chance[d])||g.chance[d]<=0||g.river[d]<0||g.river[d]>=g.r||g.rank[d]<0||g.rank[d]>=g.k)return false;
  total+=g.chance[d];
  for(int p=0;p<g.p;++p)if(g.own[d*g.p+p]<0||g.own[d*g.p+p]>=g.hands[p])return false;
 }
 if(std::abs(total-1)>1e-8)return false;
 for(int j=0;j<g.k*g.p;++j)if(g.ranks[j]<-1||g.ranks[j]>=g.p)return false;
 return true;
}
int count(const TurnInput &g,int n){return g.at[n+1]-g.at[n];}
int offset(const TurnInput &g,int n,int d) {
 int a=g.actor[n],h=g.own[d*g.p+a];
 return g.base[n]+((g.street[n]?g.river[d]*g.hands[a]:0)+h)*count(g,n);
}
double terminal(const TurnInput &g,int n,int d,int p) {
 return g.utility[(size_t(g.term[n])*g.k+g.rank[d])*g.p+p];
}
struct Solver {
 const TurnInput &g;double *policy;std::vector<double> regret,average;
 std::vector<std::vector<double>> mass;
 std::array<double,6> reach;
 uint64_t visits=0,limit;int target=0,iteration=0,deal=0;
 Solver(const TurnInput &x,double *out,uint64_t budget):g(x),policy(out),regret(x.slots,0),average(x.slots,0),mass(x.p),limit(budget) {
  for(int p=0;p<g.p;++p)mass[p].assign(g.hands[p]*(g.r+1),0);
  for(int d=0;d<g.d;++d)for(int p=0;p<g.p;++p) {
   int h=g.own[d*g.p+p];mass[p][h]+=g.chance[d];
   mass[p][g.hands[p]*(g.river[d]+1)+h]+=g.chance[d];
  }
 }
 void tick(){if(++visits>limit)throw Budget();}
 double visit(int n) {
  tick();int a=g.actor[n],c=count(g,n);
  if(a==-1)return terminal(g,n,deal,target);
  if(g.prune[n]&(1<<target))return -g.initial[target]-g.paid[n*g.p+target];
  if(a==-2||c==1)return visit(g.child[g.at[n]]);
  int start=offset(g,n,deal);double saved=reach[a],value=0;std::array<double,6> v{};
  for(int j=0;j<c;++j) {
   double probability=policy[start+j];
   // An opponent's zero-probability edge has zero counterfactual reach.
   if(a!=target&&probability==0)continue;
   reach[a]=saved*probability;v[j]=visit(g.child[g.at[n]+j]);value+=probability*v[j];
  }
  reach[a]=saved;
  if(a==target) {
   double cf=g.chance[deal];for(int p=0;p<g.p;++p)if(p!=target)cf*=reach[p];
   // Clip only after the entire target pass. The policy stays frozen meanwhile.
   for(int j=0;j<c;++j)regret[start+j]+=cf*(v[j]-value);
  }
  return value;
 }
 void avg(int n,int h,int river,double own_reach) {
  tick();if(own_reach==0||!(g.mask[n]&(1<<target)))return;
  int a=g.actor[n],c=count(g,n);if(a==-1)return;
  if(a==-2) {
   for(int r=0;r<g.r;++r)if(mass[target][g.hands[target]*(r+1)+h]>0)avg(g.child[g.at[n]],h,r,own_reach);
   return;
  }
  if(a==target&&c>1) {
   int slot=g.base[n]+((g.street[n]?river*g.hands[target]:0)+h)*c;
   double chance=mass[target][g.hands[target]*(g.street[n]?river+1:0)+h];
   for(int j=0;j<c;++j) {
    average[slot+j]+=iteration*chance*own_reach*policy[slot+j];
    avg(g.child[g.at[n]+j],h,river,own_reach*policy[slot+j]);
   }
  } else for(int j=g.at[n];j<g.at[n+1];++j)avg(g.child[j],h,river,own_reach);
 }
 void update() {
  for(int n=0;n<g.n;++n)if(g.actor[n]==target&&count(g,n)>1) {
   int c=count(g,n),end=g.base[n]+c*g.hands[target]*(g.street[n]?g.r:1);
   for(int start=g.base[n];start<end;start+=c) {
    double sum=0;for(int j=0;j<c;++j){regret[start+j]=std::max(0.,regret[start+j]);sum+=regret[start+j];}
    for(int j=0;j<c;++j)policy[start+j]=sum>0?regret[start+j]/sum:1./c;
   }
  }
 }
};
struct Weighted {int deal;double weight;};
struct Evaluation {
 const TurnInput &g;const double *policy;uint64_t visits=0,limit;int target;
 void tick(){if(++visits>limit)throw Budget();}
 std::array<double,2> eval(int n,const std::vector<Weighted> &weights,bool best=true) {
  tick();if(weights.empty())return {0,0};
  int a=g.actor[n],c=count(g,n);
  if(a==-1) {
   double total=0;for(auto w:weights)total+=w.weight*terminal(g,n,w.deal,target);
   return {total,total};
  }
  if(g.prune[n]&(1<<target)) {
   double total=0;for(auto w:weights)total+=w.weight;
   total*=-g.initial[target]-g.paid[n*g.p+target];return {total,total};
  }
  if(a==-2) {
   std::vector<std::vector<Weighted>> groups(g.r);
   for(auto w:weights)groups[g.river[w.deal]].push_back(w);
   std::array<double,2> sum{0,0};
   for(auto &group:groups)if(!group.empty()) {
    auto value=eval(g.child[g.at[n]],group,best);sum[0]+=value[0];sum[1]+=value[1];
   }
   return sum;
  }
  if(c==1)return eval(g.child[g.at[n]],weights,best);
  if(a==target) {
   int start=offset(g,n,weights[0].deal);double pp=0,br=-1e300;
   for(int j=0;j<c;++j) {
    if(!best&&policy[start+j]==0)continue;
    auto value=eval(g.child[g.at[n]+j],weights,best);
    pp+=policy[start+j]*value[0];br=std::max(br,value[1]);
   }
   return {pp,best?br:pp};
  }
  std::array<double,2> sum{0,0};std::vector<Weighted> next;next.reserve(weights.size());
  for(int j=0;j<c;++j) {
   next.clear();
   for(auto w:weights) {
    double p=policy[offset(g,n,w.deal)+j];
    if(p>0)next.push_back({w.deal,w.weight*p});
   }
   if(!next.empty()) {
    auto value=eval(g.child[g.at[n]+j],next,best);sum[0]+=value[0];sum[1]+=value[1];
   }
  }
  return sum;
 }
};
}
extern "C" int poker_turn_abi(){return 2;}
extern "C" int poker_turn_utilities(const TurnInput *input) {
 try {
  const auto &g=*input;if(!valid(g))return 2;
  for(int t=0;t<g.t;++t) {
   std::array<int,6> paid{},refund{},total{};int high=0,second=-1;
   for(int p=0;p<g.p;++p){paid[p]=g.state_paid[t*g.p+p];if(paid[p]>paid[high])high=p;}
   for(int p=0;p<g.p;++p)if(p!=high)second=std::max(second,paid[p]);
   refund[high]=paid[high]-second;paid[high]=second;
   std::vector<int> levels;
   for(int p=0;p<g.p;++p){total[p]=g.initial[p]+paid[p];if(total[p]>0)levels.push_back(total[p]);}
   std::sort(levels.begin(),levels.end());levels.erase(std::unique(levels.begin(),levels.end()),levels.end());
   std::vector<std::pair<int,int>> pots;int prior=0;
   for(int level:levels) {
    int contributors=0,eligible=0;
    for(int p=0;p<g.p;++p)if(total[p]>=level){++contributors;if(g.state_mask[t]&(1<<p))eligible|=1<<p;}
    int amount=(level-prior)*contributors;prior=level;if(!eligible)return 2;
    if(!pots.empty()&&pots.back().first==eligible)pots.back().second+=amount;else pots.push_back({eligible,amount});
   }
   for(int k=0;k<g.k;++k) {
    std::array<int,6> awards=refund;
    for(auto pot:pots) {
     int best=-2,winners=0;
     for(int p=0;p<g.p;++p)if(pot.first&(1<<p))best=std::max(best,g.ranks[k*g.p+p]);
     for(int p=0;p<g.p;++p)if((pot.first&(1<<p))&&g.ranks[k*g.p+p]==best)++winners;
     if(best<0||!winners)return 2;
     int share=pot.second/winners,remainder=pot.second%winners;
     for(int j=1;j<=g.p;++j) {
      int p=(g.button+j)%g.p;
      if((pot.first&(1<<p))&&g.ranks[k*g.p+p]==best){awards[p]+=share+(remainder>0);if(remainder>0)--remainder;}
     }
    }
    double sum=0;
    for(int p=0;p<g.p;++p) {
     int32_t value=awards[p]-g.state_paid[t*g.p+p]-g.initial[p];sum+=value;
     g.utility[(size_t(t)*g.k+k)*g.p+p]=value;
    }
    if(sum!=0)return 2;
   }
  }
  return 0;
 }catch(...){return 3;}
}
extern "C" int poker_turn_train(const TurnInput *input,int iterations,uint64_t limit,double *output,uint64_t *visits) {
 try {
  const auto &g=*input;if(!valid(g)||iterations<1||iterations>2000||limit<1)return 2;
  for(int n=0;n<g.n;++n)if(g.actor[n]>=0&&count(g,n)>1) {
   int c=count(g,n),end=g.base[n]+c*g.hands[g.actor[n]]*(g.street[n]?g.r:1);
   for(int j=g.base[n];j<end;++j)output[j]=1./c;
  }
  Solver s(g,output,limit);
  try {
   for(s.iteration=1;s.iteration<=iterations;++s.iteration)for(s.target=0;s.target<g.p;++s.target) {
    bool acts=false;for(int n=0;n<g.n;++n)if(g.actor[n]==s.target&&count(g,n)>1){acts=true;break;}
    if(!acts)continue;
    for(int h=0;h<g.hands[s.target];++h)if(s.mass[s.target][h]>0)s.avg(g.root,h,-1,1);
    for(s.deal=0;s.deal<g.d;++s.deal){s.reach.fill(1);s.visit(g.root);}
    s.update();
   }
  }catch(Budget&){*visits=s.visits;return 4;}
  *visits=s.visits;
  for(int n=0;n<g.n;++n)if(g.actor[n]>=0&&count(g,n)>1) {
   int c=count(g,n),end=g.base[n]+c*g.hands[g.actor[n]]*(g.street[n]?g.r:1);
   for(int start=g.base[n];start<end;start+=c) {
    double sum=0;for(int j=0;j<c;++j)sum+=s.average[start+j];
    for(int j=0;j<c;++j)output[start+j]=sum>0?s.average[start+j]/sum:1./c;
   }
  }
  return 0;
 }catch(...){return 3;}
}
extern "C" int poker_turn_measure(const TurnInput *input,const double *policy,int probe,uint64_t limit,double *output,uint64_t *visits) {
 try {
  const auto &g=*input;if(!valid(g)||limit<1)return 2;
  for(int n=0;n<g.n;++n)if(g.actor[n]>=0&&count(g,n)>1) {
   int c=count(g,n),end=g.base[n]+c*g.hands[g.actor[n]]*(g.street[n]?g.r:1);
   for(int start=g.base[n];start<end;start+=c) {
    double sum=0;
    for(int j=0;j<c;++j){double p=policy[start+j];if(!std::isfinite(p)||p<0||p>1)return 2;sum+=p;}
    if(std::abs(sum-1)>1e-8)return 2;
   }
  }
  Evaluation e{g,policy,0,limit,0};
  try {
   for(e.target=0;e.target<g.p;++e.target) {
    output[2*e.target]=output[2*e.target+1]=0;
    for(int h=0;h<g.hands[e.target];++h) {
     std::vector<Weighted> weights;
     for(int d=0;d<g.d;++d)if(g.own[d*g.p+e.target]==h)weights.push_back({d,g.chance[d]});
     if(weights.empty())continue;
     auto value=e.eval(g.root,weights);output[2*e.target]+=value[0];output[2*e.target+1]+=value[1];
    }
   }
   if(probe>=0) {
    e.target=g.actor[g.root];if(e.target<0||probe>=g.hands[e.target])return 5;
    std::vector<Weighted> weights;double mass=0;
    for(int d=0;d<g.d;++d)if(g.own[d*g.p+e.target]==probe){weights.push_back({d,g.chance[d]});mass+=g.chance[d];}
    if(mass<=0)return 5;
    int c=count(g,g.root);double sunk=g.initial[e.target]+g.paid[g.root*g.p+e.target];
    for(int j=0;j<c;++j)output[2*g.p+j]=e.eval(g.child[g.at[g.root]+j],weights,false)[0]/mass+sunk;
    output[2*g.p+c]=mass;
   }
  }catch(Budget&){*visits=e.visits;return 4;}
  *visits=e.visits;return 0;
 }catch(...){return 3;}
}
