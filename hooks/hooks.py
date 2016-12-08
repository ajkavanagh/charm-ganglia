#!/usr/bin/python3

import sys
import subprocess
import os

import charmhelpers.core.hookenv as hookenv
import charmhelpers.core.host as host
import charmhelpers.fetch as fetch

TEMPLATES_DIR = 'templates'

try:
    import jinja2
except ImportError:
    fetch.apt_install('python3-jinja2', fatal=True)
    import jinja2


def render_template(template_name, context, template_dir=TEMPLATES_DIR):
    templates = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir)
    )
    template = templates.get_template(template_name)
    return template.render(context)


# Services
GMETAD = "gmetad"
GMOND = "ganglia-monitor"
APACHE = "apache2"

APACHE_CONFIG = "/etc/apache2/sites-available/ganglia.conf"
GANGLIA_APACHE_CONFIG = "/etc/ganglia-webfrontend/apache.conf"
GMOND_CONF = "/etc/ganglia/gmond.conf"
GMETAD_CONF = "/etc/ganglia/gmetad.conf"

RESTART_MAP = {
    GMETAD_CONF: [GMETAD],
    GMOND_CONF: [GMOND]
}

PACKAGES = [
    "ganglia-webfrontend",
    GMETAD,
    GMOND,
]

hooks = hookenv.Hooks()


@hooks.hook('update-status')
def assess_status():
    '''Assess status of current unit'''
    hookenv.application_version_set(fetch.get_upstream_version(GMETAD))
    if host.service_running(GMETAD):
        hookenv.status_set('active', 'Unit is ready')
    else:
        hookenv.status_set('blocked',
                           '{} not running'.format(GMETAD))


@hooks.hook("master-relation-departed",
            "master-relation-broken",
            "master-relation-changed",
            "ganglia-node-relation-changed",
            "ganglia-node-relation-joined")
@host.restart_on_change(RESTART_MAP)
def configure_gmetad():
    hookenv.log("Configuring gmetad for master unit")
    data_sources = {
        "self": ["localhost"]
    }
    for _rid in hookenv.relation_ids("master"):
        for _unit in hookenv.related_units(_rid):
            # endpoint is set by ganglia-node
            # subordinate to indicate that
            # gmond should not be used as a
            # datasource
            _datasource = hookenv.relation_get('datasource',
                                               _unit, _rid)
            if _datasource == "true":
                service_name = _unit.split('/')[0]
                if service_name not in data_sources:
                    data_sources[service_name] = []
                data_sources[service_name]\
                    .append(hookenv.relation_get('private-address',
                                                 _unit, _rid))

    context = {
        "data_sources": data_sources,
        "gridname": hookenv.config("gridname")
    }

    with open(GMETAD_CONF, "w") as gmetad:
        gmetad.write(render_template("gmetad.conf", context))


@hooks.hook("head-relation-departed",
            "head-relation-broken")
@host.restart_on_change(RESTART_MAP)
def configure_gmond():
    hookenv.log("Configuring ganglia monitoring daemon")
    masters = []
    # Configure as head unit and send data to masters
    for _rid in hookenv.relation_ids("head"):
        for _master in hookenv.related_units(_rid):
            masters.append(hookenv.relation_get('private-address',
                                                _master, _rid))
    context = {
        "service_name": hookenv.service_name(),
        "masters": masters,
        "dead_host_timeout": hookenv.config("dead_host_timeout")
    }

    with open(GMOND_CONF, "w") as gmond:
        gmond.write(render_template("gmond.conf", context))


def configure_apache():
    hookenv.log("Configuring apache vhost for ganglia master")
    if not os.path.exists(APACHE_CONFIG):
        os.symlink(GANGLIA_APACHE_CONFIG, APACHE_CONFIG)
        command = [
            'a2ensite',
            os.path.basename(APACHE_CONFIG)
        ]
        subprocess.check_call(command)
    host.service_reload(APACHE)


def expose_ganglia():
    hookenv.open_port(80)


def install_ganglia():
    fetch.apt_install(PACKAGES, fatal=True)


# Hook helpers for dict lookups for switching
@hooks.hook('install')
def install_hook():
    install_ganglia()
    configure_gmond()
    configure_gmetad()
    configure_apache()
    expose_ganglia()


@hooks.hook('website-relation-joined')
def website_hook():
    hookenv.relation_set(port=80,
                         hostname=hookenv.unit_get("private-address"))


@hooks.hook('upgrade-charm')
def upgrade_hook():
    configure_gmond()
    configure_gmetad()
    expose_ganglia()


@hooks.hook('head-relation-joined')
def head_hook():
    hookenv.relation_set(datasource="true")
    configure_gmond()


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except hookenv.UnregisteredHookError as e:
        hookenv.log('Unknown hook {} - skipping.'.format(e),
                    hookenv.DEBUG)
    assess_status()
