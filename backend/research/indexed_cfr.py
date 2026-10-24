"""Indexed CFR+ traversal for the bounded research tree, not a new game model.
Keeps exact chance enumeration, update boundaries and public information sets.
"""


def train_indexed(game,iterations):
    if type(iterations) is not int or not 1<=iterations<=2000:
        raise ValueError('1–2000 iterations required.')
    # Compilation is part of training time; no warmed cache is assumed.
    nodes=game.nodes;indices={id(node):i for i,node in enumerate(nodes)}
    root=indices[id(game.root)];actors=[node.actor for node in nodes]
    children=[tuple(indices[id(child)] for child in node.children) for node in nodes]
    edges=[child for row in children for child in row]
    if len(edges)!=len(nodes)-1 or len(set(edges))!=len(edges) or root in edges:
        raise ValueError('Indexed buffers require a tree with one parent per non-root node.')
    info_keys=sorted(game.keys);info_index={key:i for i,key in enumerate(info_keys)}
    counts=[game.action_counts[key] for key in info_keys]
    owned=[[i for i,key in enumerate(info_keys) if key[0]==p] for p in range(game.n)]
    deal_infos=[];deal_utilities=[]
    for deal in range(len(game.deals)):
        deal_infos.append([info_index[game.key(node,deal)] if node.actor!=-1 else -1 for node in nodes])
        deal_utilities.append([game.utilities[(id(node),deal)] if node.actor==-1 else None for node in nodes])
    regrets=[[0.]*m for m in counts];average=[[0.]*m for m in counts]
    policy=[[1/m]*m for m in counts]
    # Every public node has one parent: child recursion cannot overwrite its
    # parent's action buffer. Buffers are fully rewritten before each use.
    buffers=[[0.]*len(child) for child in children]
    for iteration in range(1,iterations+1):
        for target,information_sets in enumerate(owned):
            if not information_sets:continue # folded/all-in seats have no decisions
            delta=[None]*len(info_keys)
            for i in information_sets:delta[i]=[0.]*counts[i]
            def visit(index):
                actor=actors[index]
                if actor==-1:return utilities[index][target]
                info=infos[index];strategy=policy[info];values=buffers[index]
                saved=reach[actor]
                for a,child in enumerate(children[index]):
                    reach[actor]=saved*strategy[a]
                    values[a]=visit(child)
                reach[actor]=saved
                value=0.
                for a,probability in enumerate(strategy):value+=probability*values[a]
                if actor==target:
                    other_reach=1.
                    for p in range(game.n):
                        if p!=actor:other_reach*=reach[p]
                    counterfactual=chance*other_reach
                    changes=delta[info];sums=average[info]
                    for a,probability in enumerate(strategy):
                        changes[a]+=counterfactual*(values[a]-value)
                        sums[a]+=iteration*chance*saved*probability
                return value
            # Freeze policy for all chance deals, then update this player only.
            for deal,(_,chance,_) in enumerate(game.deals):
                infos=deal_infos[deal];utilities=deal_utilities[deal];reach=[1.]*game.n
                visit(root)
            for info in information_sets:
                row=regrets[info];changes=delta[info]
                for a in range(len(row)):row[a]=max(0.,row[a]+changes[a])
                total=sum(row);policy[info]=[v/total for v in row] if total else [1/len(row)]*len(row)
    return {key:([v/sum(row) for v in row] if sum(row)>0 else [1/len(row)]*len(row))
            for key,row in zip(info_keys,average)}
