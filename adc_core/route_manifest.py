"""Static route walk for packaging/fixture checks; not runtime authorization."""
import ast

def named_routes(root, module='config.urls', prefix='', seen=None):
    seen=set() if seen is None else seen
    if module in seen:return {}
    seen.add(module)
    tree=ast.parse((root / (module.replace('.','/')+'.py')).read_text(encoding='utf-8'))
    routes={}
    for node in ast.walk(tree):
        if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='path' and len(node.args)>=2 and isinstance(node.args[0],ast.Constant)):
            continue
        path=prefix+node.args[0].value
        for kw in node.keywords:
            if kw.arg=='name' and isinstance(kw.value,ast.Constant):routes[kw.value.value]='/'+path
        target=node.args[1]
        if isinstance(target,ast.Call) and isinstance(target.func,ast.Name) and target.func.id=='include' and target.args and isinstance(target.args[0],ast.Constant):
            routes.update(named_routes(root,target.args[0].value,path,seen))
    return routes
