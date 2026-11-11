"""Resolved-host LOCAL-session association simulations, not deployed auth."""
from enum import Enum
from types import SimpleNamespace
from pathlib import Path
from studio.domain import Fault
from studio.native.backend.scope import NativePorts
from tests.test_connector_synthesis import SynthesisFixture


class Platform(Enum):
    LOCAL = 'local'
    TELEGRAM = 'telegram'


class NativeScopeTests(SynthesisFixture):
    def setUp(self):
        super().setUp()
        self.host_home = Path(self.temp.name)/'resolved-host'
        self.ctx = SimpleNamespace(plugin_id='motion-studio', _manager=SimpleNamespace(home_path=self.host_home))
        self.authority = SimpleNamespace(profile_id=str(self.host_home), retiring=False,
            sessions={self.scope.session:SimpleNamespace(source=SimpleNamespace(platform=Platform.LOCAL))})
        self.epochs = {self.scope.session:1}
        self.ports = NativePorts(home=self.host_home, workspace=self.store.home,
            profile_reference=self.scope.profile, service=self.service, enabled=lambda:True,
            audience_reviewed=lambda:True, session_epochs=lambda:self.epochs, authority=lambda:self.authority)

    def test_resolved_manager_home_profile_and_local_session(self):
        self.assertEqual(self.ports.resolve(self.ctx, self.scope.session)[0], self.scope)
        self.ctx._manager.home_path = self.host_home/'other'
        with self.assertRaises(Fault): self.ports.resolve(self.ctx, self.scope.session)

    def test_isolated_context_missing_authority_is_unavailable_not_default(self):
        remote = SimpleNamespace(plugin_id='motion-studio', profile_name='fixture-profile')
        with self.assertRaisesRegex(Fault, 'SYNTHESIS_UNAVAILABLE'):
            self.ports.resolve(remote, self.scope.session)
        self.assertFalse(self.facade.calls)

    def test_remote_missing_disabled_audience_and_unassociated_workspace(self):
        for mutation in ('remote', 'missing', 'profile', 'disabled', 'audience', 'workspace', 'epoch'):
            with self.subTest(mutation=mutation):

                if mutation == 'remote': self.authority.sessions[self.scope.session].source.platform = Platform.TELEGRAM
                if mutation == 'missing': self.authority.sessions.clear()
                if mutation == 'profile': self.authority.profile_id = str(self.host_home/'other')
                if mutation == 'disabled': self.ports.enabled = lambda:False
                if mutation == 'audience': self.ports.audience_reviewed = lambda:False
                if mutation == 'workspace': self.ports.workspace = self.store.home/'unassociated'
                if mutation == 'epoch': self.epochs.clear()
                with self.assertRaises(Fault): self.ports.resolve(self.ctx, self.scope.session)
                self.authority.profile_id = str(self.host_home)
                self.authority.sessions[self.scope.session] = SimpleNamespace(source=SimpleNamespace(platform=Platform.LOCAL))
                self.ports.enabled = self.ports.audience_reviewed = lambda:True
                self.ports.workspace = self.store.home
                self.epochs[self.scope.session] = 1
        self.assertFalse(self.facade.calls)
