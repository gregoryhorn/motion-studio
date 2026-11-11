"""Pinned host root functions on synthetic lineage; no host launch or model calls."""
import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest
from tests.creation_support import Context, setup, effects

HOST = Path(os.environ.get('HERMES_SOURCE',Path.home()/'.hermes/hermes-agent-official'))


class CanonicalRootTests(unittest.TestCase):
    def test_shipped_schema_survives_actual_pinned_host_sanitizer(self):
        import importlib.util
        from studio.native.creation.registration import register
        spec=importlib.util.spec_from_file_location('motion_host_schema_sanitizer',HOST/'tools/schema_sanitizer.py')
        assert spec and spec.loader
        sanitizer=importlib.util.module_from_spec(spec);spec.loader.exec_module(sanitizer)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        ctx=Context(Path(temp.name)/'registration-must-stay-inert');runtime=register(ctx);self.addCleanup(runtime.unload)
        shipped=ctx.tools['motion_studio_creation'][0]
        visible=sanitizer.sanitize_tool_schemas([dict(type='function',function=shipped)])[0]['function']['parameters']
        required={'operation','direction','seconds','seed','parent','request','revision','command','run',
                  'schema_version','kind','instrumental','reference_requested','method','method_id','submission','attempt','conversion_ok','path','url','data','tool'}
        self.assertEqual(set(visible['properties']),required)
        self.assertEqual(visible['properties']['operation']['enum'],['prepare','start','status','stop','collect_output'])
        self.assertEqual(visible['required'],['operation'])
        self.assertNotIn('default',visible['properties']['seconds'])
        self.assertEqual(visible['properties']['kind']['enum'],['Music','Image','Voice','Video'])
        self.assertEqual(visible['properties']['seed']['default'],42)
        self.assertEqual(visible['type'],'object')
        self.assertFalse(visible['additionalProperties'])

    def test_real_compression_walk_gateway_pair_and_delegate_assignment(self):
        sys.path.append(str(HOST))
        from agent.prompt_cache_scope import conversation_id
        # unittest already imports this repository's tools namespace. Include
        # the pinned host's tools for its own imports, without replacing ours.
        import tools
        host_tools = str(HOST / 'tools')
        original_tools_path = tools.__path__
        tools.__path__ = [*original_tools_path, host_tools]
        self.addCleanup(setattr, tools, '__path__', original_tools_path)
        from hermes_state import SessionDB
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            db=SessionDB(db_path=root/'synthetic-host.db')
            ctx,runtime,binding=setup(root/'app')
            try:
                db.create_session('canonical-root',source='cli')
                db.end_session('canonical-root','compression')
                db.create_session('physical-compressed',source='cli',parent_session_id='canonical-root')
                parent=SimpleNamespace(session_id='physical-compressed',_session_db=db)
                self.assertEqual(conversation_id(parent),'canonical-root')
                # Execute the exact pinned gateway logical-owner implementation,
                # without importing private gateway code into the application.
                tree=ast.parse((HOST/'gateway/session_authority.py').read_text())
                function=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='logical_owner')
                namespace={};exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(HOST/'gateway/session_authority.py'),'exec'),namespace)
                authorized_root=namespace['logical_owner'](SimpleNamespace(db=db),'physical-compressed')
                self.assertEqual(authorized_root,conversation_id(parent))
                ctx.methods['creation.admit']({},session_id=authorized_root)
                # Execute the actual delegate spawn's inherited-root assignment,
                # not a guessed physical-session alias or synthetic root resolver.
                tree=ast.parse((HOST/'tools/delegate_tool.py').read_text())
                statement=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(
                    isinstance(t,ast.Attribute) and t.attr=='_inherited_conversation_id' for t in n.targets))
                child=SimpleNamespace(session_id='delegated-physical',_session_db=db)
                namespace=dict(child=child,parent_agent=parent,conversation_id=conversation_id)
                exec(compile(ast.fix_missing_locations(ast.Module(body=[statement],type_ignores=[])),str(HOST/'tools/delegate_tool.py'),'exec'),namespace)
                handler=ctx.tools['motion_studio_creation'][1]
                import json
                first=json.loads(handler(dict(operation='prepare',direction='Synthetic door slam'),
                    session_id=parent.session_id,conversation_id=conversation_id(parent)))
                recovered=json.loads(handler(dict(operation='status'),session_id=child.session_id,conversation_id=conversation_id(child)))
                self.assertEqual(first['command'],recovered['command'])
                self.assertEqual(ctx.methods['creation.status']({},session_id=authorized_root)['request'],first['request'])
                # Branch/new root and a physical-ID-only caller do not inherit access.
                db.create_session('branched-root',source='cli',parent_session_id='physical-compressed')
                branch=SimpleNamespace(session_id='branched-root',_session_db=db)
                self.assertEqual(conversation_id(branch),'branched-root')
                self.assertIn('error',json.loads(handler(dict(operation='status'),session_id='branched-root',conversation_id=conversation_id(branch))))
                self.assertIn('error',ctx.methods['creation.status']({},session_id='physical-compressed'))
                self.assertEqual(effects(binding),[])
            finally:
                runtime.unload();db.close()


if __name__=='__main__': unittest.main()
