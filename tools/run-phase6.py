#!/usr/bin/env python3
"""Bounded standalone packaging and isolated Boot consumers. No Docker or publication."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import stat
import urllib.error
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
MODULES = ('core', 'udak-api', 'jdbc-spring', 'observe-core', 'starter-boot3', 'starter-boot4')
GRADLE_VERSION = '8.14.3'
GRADLE_SHA256 = 'bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531'
MANIFEST = 'tools/phase6-dependencies.json'
REPORT = 'evidence/PHASE6-VALIDATION.json'
HARNESS = ('tools/run-phase6.py', 'tools/verify-phase6.py', 'tools/test-phase6-verifier.py',
           'tools/local-ci.py', 'tools/udak-cli.py', 'tools/release-gate.py', 'tools/test-phase6-cli.py',
           'udak-cli/udak_cli.py', 'tools/run-phase1.py', 'tools/run-phase3.py', 'tools/run-phase4.py',
           'tools/run-phase5.py', 'tools/verify-phase5.py')
CONFIG = ('settings.gradle.kts', 'build.gradle.kts', 'starter-testkit/settings.gradle', 'starter-testkit/build.gradle',
          'starter-boot3/build.gradle.kts', 'starter-boot4/build.gradle.kts') + tuple(m+'/build.gradle.kts' for m in MODULES[:4]) + tuple(
          m+'/src/main/resources/META-INF/'+n for m in MODULES[-2:] for n in
          ('spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports','spring-configuration-metadata.json'))
CANDIDATE_BASE = None
PEAK = {'files':0,'bytes':0}
JAVA = ['java', '-Xmx256m', '-XX:MaxMetaspaceSize=128m', '-XX:ActiveProcessorCount=2']

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

p5 = module('phase6_previous', 'tools/run-phase5.py')
guard = p5.guard

def sources():
    paths = p5.source_paths()
    for m in ('starter-boot3', 'starter-boot4', 'starter-testkit'):
        paths |= {str(p.relative_to(ROOT)) for p in (ROOT/m/'src').rglob('*.java')}
    return paths

def hashes(names):
    return p5.hashes(names)

def save(path, value):
    (ROOT/path).parent.mkdir(parents=True,exist_ok=True)
    p5.archive_save(ROOT/path, value)

def download_allowed(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443):return False
    if parsed.hostname=='repo.maven.apache.org':return parsed.path.startswith('/maven2/')
    if parsed.hostname=='downloads.gradle.org':return parsed.path=='/distributions/gradle-'+GRADLE_VERSION+'-bin.zip'
    if parsed.hostname=='github.com':return parsed.path=='/gradle/gradle-distributions/releases/download/v'+GRADLE_VERSION+'/gradle-'+GRADLE_VERSION+'-bin.zip'
    return parsed.hostname=='release-assets.githubusercontent.com' and parsed.path.startswith('/github-production-release-asset/')

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not download_allowed(newurl):raise ValueError('Download redirect denied')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url, maximum=1024*1024):
    if not download_allowed(url):raise ValueError('Download origin denied')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),SafeRedirect())
    with opener.open(url,timeout=30) as response:
        if not download_allowed(response.geturl()):raise ValueError('Download redirect denied')
        content=response.read(maximum+1)
    if len(content)>maximum:raise ValueError('Download bound exceeded')
    return content

def gradle_distribution(work):
    url = 'https://downloads.gradle.org/distributions/gradle-'+GRADLE_VERSION+'-bin.zip'
    raw = fetch(url, 160*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=GRADLE_SHA256:
        raise ValueError('Gradle distribution checksum mismatch')
    path = work/'gradle.zip'
    path.write_bytes(raw)
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries)>1500 or sum(i.file_size for i in entries)>200*1024*1024:
            raise ValueError('Gradle archive bounds exceeded')
        for item in entries:
            parts = Path(item.filename).parts
            if not parts or parts[0]!='gradle-'+GRADLE_VERSION or '..' in parts or Path(item.filename).is_absolute() or (item.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Gradle archive path denied')
        archive.extractall(work)
    binary = work/('gradle-'+GRADLE_VERSION)/'bin/gradle'
    binary.chmod(0o700)
    path.unlink()
    return str(binary)

def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (120,120))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256*1024*1024,256*1024*1024))

def child_environment(work):
    java=Path(shutil.which('java')).resolve()
    return {'PATH':str(java.parent)+':'+str(Path(sys.executable).parent)+':/usr/bin:/bin:/usr/sbin:/sbin',
            'JAVA_HOME':str(java.parent.parent),'TMPDIR':str(work),'GRADLE_USER_HOME':str(work/'home'),
            'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','JAVA_OPTS':'-Duser.home='+str(work/'user-home')}

def step(name, command, work, timeout=60, expected=0, monitor=True):
    log=work/(name+'.output')
    with log.open('wb') as stream:
        guard.CURRENT=subprocess.Popen(command,cwd=ROOT,env=child_environment(work),stdout=stream,
            stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True,preexec_fn=limits)
        try:
            deadline=time.monotonic()+timeout
            while True:
                try:
                    code=guard.CURRENT.wait(timeout=min(2,max(0.001,deadline-time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    inventory=bounded_inventory(work,transient=True) if monitor else []
                    PEAK['files']=max(PEAK['files'],len(inventory))
                    PEAK['bytes']=max(PEAK['bytes'],sum(info.st_size for _,info in inventory if stat.S_ISREG(info.st_mode)))
                    if time.monotonic()>=deadline:raise

        except subprocess.TimeoutExpired:
            guard.stop_child();code=124
        finally:
            process=guard.CURRENT
            guard.stop_child()
            guard.CURRENT=None
    if log.stat().st_size>1024*1024:raise ValueError('Output bound exceeded')
    output=log.read_bytes()
    record={'name':name,'status':'PASS' if code==expected else 'FAIL','exit_code':code,
            'child_reaped':process.poll() is not None,'process_group_quiesced':not guard.group_alive(process.pid),
            'output_sha512':guard.digest(output)}
    if code!=expected:
        safe=[]
        for line in output.decode('utf-8',errors='replace').splitlines():
            # Compiler locations/categories only. Never copy exception messages or raw app logs.
            match=re.search(r'(?:([A-Za-z0-9_]+\.(?:java|gradle|kts)):(\d+))',line)
            if match:safe.append({'file':match[1],'line':int(match[2])})
        record['diagnostic_locations']=safe[:10]
        record['application_diagnostics']=[line for line in output.decode('utf-8',errors='replace').splitlines()
            if re.fullmatch(r'(?:BOOT[34] FAIL|SCENARIO=[A-Z_]+:FAIL|DIAGNOSTIC=[A-Za-z0-9_.$]+(?::[0-9]+)?)',line)][:12]
        record['categories']=[label for label,needle in [('COMPILATION','Compilation failed'),('RESOLUTION','Could not resolve'),
            ('TASK','Execution failed for task'),('MISSING_ARTIFACT','Could not find'),('SCRIPT','Could not compile'),
            ('TIMEOUT','timed out'),('JAVA_HOME','JAVA_HOME is set to an invalid directory'),('DAEMON','daemon disappeared'),('JDK','Unsupported class file major version')] if needle.encode() in output]
        record['reason_codes']=[label for label,needle in (
            ('PUBLISH_LIFECYCLE','Cannot run Project.afterEvaluate'),
            ('NO_JAVA_TOOLCHAIN','Cannot find a Java installation'),
            ('UNSUPPORTED_JAVA','Unsupported class file major version'),
            ('DEPENDENCY_NOT_FOUND','Could not find '),
            ('NETWORK_RESOLUTION','Could not resolve '),
            ('DAEMON_DISAPPEARED','daemon disappeared')) if needle.encode() in output]
        raise RuntimeError(json.dumps(record))
    return record

def bounded_inventory(base, maximum=20000, byte_limit=2*1024**3, transient=False):
    result=[];total=0
    root_info=base.lstat()
    if not stat.S_ISDIR(root_info.st_mode):raise ValueError('Workspace root denied')
    device=root_info.st_dev
    pending=[base]
    while pending:
        directory=pending.pop()
        try:iterator=os.scandir(directory)
        except FileNotFoundError:
            if transient:continue
            raise
        with iterator as entries:
            for entry in entries:
                try:info=entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    if transient:continue
                    raise
                if len(result)>=maximum or info.st_dev!=device or stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise ValueError('Workspace identity or entry bound denied')
                if re.search(r'(?:^|[._-])(?:env|credentials?|passwords?|secrets?|tokens?)(?:[._-]|$)',entry.name,re.I):
                    raise ValueError('Private material preserved')
                path=Path(entry.path)
                result.append((path,info))
                if stat.S_ISDIR(info.st_mode):pending.append(path)
                else:
                    if info.st_nlink!=1:raise ValueError('Linked material preserved')
                    total+=info.st_size
                    if total>byte_limit:raise ValueError('Workspace byte bound exceeded')
    return result

@contextmanager
def workspace():
    temp = tempfile.TemporaryDirectory(prefix='udak-phase6-',dir=Path('/tmp').resolve())
    work = Path(temp.name).resolve()
    cleanup = {}
    try:
        yield work, cleanup
    finally:
        try:
            guard.stop_child()
            binary=work/('gradle-'+GRADLE_VERSION)/'bin/gradle'
            if binary.is_file() and (work/'home').exists():
                cleanup['gradle_stop']=step('cleanup-gradle-stop',[str(binary),'--stop','--gradle-user-home',str(work/'home')],work,timeout=30,monitor=False)
                live=[]
                for log in (work/'home/daemon'/GRADLE_VERSION).glob('daemon-*.out.log'):
                    match=re.fullmatch(r'daemon-([0-9]+)\.out\.log',log.name)
                    if match:
                        try:os.kill(int(match[1]),0);live.append(int(match[1]))
                        except ProcessLookupError:pass
                cleanup['gradle_daemons_quiesced']=not live
                if live:raise ValueError('Owned Gradle daemon shutdown unconfirmed')
            if any(p.is_dir() and p.name.startswith('udak-') for p in work.iterdir()):
                raise ValueError('Nested preserved workspace retained')
            if (work/'candidate').is_dir():
                marker=work/'candidate'/'.owner'
                info=marker.lstat()
                if (work/'candidate').is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=len(work.name) or marker.read_text()!=work.name:
                    raise ValueError('Candidate ownership unconfirmed')
                candidate_inventory()
            entries = bounded_inventory(work)
            files = [p for p,info in entries if stat.S_ISREG(info.st_mode)]
            size = sum(info.st_size for _,info in entries if stat.S_ISREG(info.st_mode))
            if (work/'candidate').is_dir():
                candidate_entries=bounded_inventory(work/'candidate',500,200*1024**2)
                cleanup['candidate_files_removed']=sum(stat.S_ISREG(info.st_mode) for _,info in candidate_entries)
                cleanup['candidate_bytes_removed']=sum(info.st_size for _,info in candidate_entries if stat.S_ISREG(info.st_mode))
            # Gradle --no-daemon is stopped before entering this finalizer.
            temp.cleanup()
            cleanup.update(status='PASS', temporary_files_removed=len(files), temporary_bytes_removed=size,
                           temporary_directory_remaining=work.exists(),peak_files=PEAK['files'],peak_bytes=PEAK['bytes'])
        except BaseException:
            temp._finalizer.detach()
            cleanup.update(status='PRESERVED_UNKNOWN', temporary_directory_remaining=True,preservation_id=work.name)
            raise

def gradle_command(binary, work, project, *tasks):
    return [binary, '--no-daemon', '--console=plain', '--max-workers=1', '--no-watch-fs',
            '--gradle-user-home', str(work/'home'), '--project-cache-dir', str(work/'cache'/project.name),
            '-Dorg.gradle.jvmargs=-Xmx512m -XX:MaxMetaspaceSize=256m -XX:ActiveProcessorCount=2',
            '-Dorg.gradle.java.installations.auto-download=false', '-p', str(project),
            '-PudakBuildRoot='+str(work/'build'), '-PudakRepository='+str(CANDIDATE_BASE/'repository'),
            '-PudakResolution='+str(work/'resolution.json'), *tasks]

def coordinate_url(group,name,version):
    if not all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',part) and '..' not in part for part in (group,name,version)):
        raise ValueError('Coordinate denied')
    return 'https://repo.maven.apache.org/maven2/'+group.replace('.','/')+'/'+name+'/'+version+'/'+name+'-'+version

def pom_licenses(group,name,version):
    import xml.etree.ElementTree as ET
    chain=[]
    ns={'m':'http://maven.apache.org/POM/4.0.0'}
    for _ in range(5):
        url=coordinate_url(group,name,version)+'.pom'
        if any(item['url']==url for item in chain):raise ValueError('Parent cycle denied')
        pom=fetch(url)
        tree=ET.fromstring(pom)
        for node in tree.iter():node.tag=node.tag.rsplit('}',1)[-1]
        chain.append({'url':url,'sha512':guard.digest(pom)})
        licenses=[{'name':n.findtext('name'),'url':n.findtext('url')} for n in tree.findall('licenses/license')]
        if licenses:
            if any(not isinstance(v,str) or not v or len(v)>300 or '${' in v for item in licenses for v in item.values()):raise ValueError('Unresolved license declaration')
            return chain,licenses
        parent=tree.find('parent')
        if parent is None:break
        group=parent.findtext('groupId')
        name=parent.findtext('artifactId')
        version=parent.findtext('version')
    raise ValueError('License declaration missing')

def pin_dependencies(work,pom_consumers=False):
    resolution=json.loads((work/'resolution.json').read_text())
    if set(resolution)!={'starter-boot3','starter-boot4','h2'}:raise ValueError('Resolution lanes incomplete')
    consumer_resolution={}
    if pom_consumers:
        for lane in ('BOOT3','BOOT4'):
            rows=json.loads((work/('consumer-'+lane)/'consumer-resolution.json').read_text())
            consumer_resolution['starter-'+lane.lower()]=[a for a in rows if a['group']!='dev.udak' and a['group']!='com.h2database']
    unique={(a['group'],a['name'],a['version']):a for lane in [*resolution.values(),*consumer_resolution.values()] for a in lane}
    if not 10<=len(unique)<=40:raise ValueError('Resolution bounds exceeded')
    records=[]
    for coord,item in sorted(unique.items()):
        group,name,version=coord
        base=coordinate_url(*coord)
        jar=Path(item['file'])
        if not jar.is_relative_to(work/'home') or jar.is_symlink() or jar.stat().st_size>24*1024**2:raise ValueError('Resolved artifact denied')
        raw=jar.read_bytes()
        algorithm=None
        for kind in ('sha512','sha256','sha1'):
            try:published=fetch(base+'.jar.'+kind,1024).decode().split()[0].lower()
            except urllib.error.HTTPError as error:
                if error.code==404:continue
                raise
            if published!=hashlib.new(kind,raw).hexdigest():raise ValueError('Published checksum mismatch')
            algorithm=kind;break
        if algorithm is None:raise ValueError('Published checksum absent')
        chain,licenses=pom_licenses(*coord)
        license_files={}
        with zipfile.ZipFile(jar) as archive:
            for entry in archive.infolist():
                if re.fullmatch(r'(?:META-INF/)?(?:LICENSE|NOTICE)(?:[._-][A-Za-z0-9-]+)?(?:\.txt)?',entry.filename,re.I):
                    if entry.file_size>512*1024 or len(license_files)>=8:raise ValueError('License resource bound exceeded')
                    license_files[entry.filename]=guard.digest(archive.read(entry))
        records.append(dict(group=group,name=name,version=version,size=len(raw),sha512=guard.digest(raw),
            pom_sha512=chain[0]['sha512'],pom_chain=chain,licenses=licenses,license_resources_sha512=license_files,
            jar_url=base+'.jar',pom_url=base+'.pom',published_checksum=algorithm))
    lanes={lane:sorted(a['group']+':'+a['name']+':'+a['version'] for a in items) for lane,items in resolution.items()}
    return {'schema_version':1,'gradle':{'version':GRADLE_VERSION,'distribution_sha256':GRADLE_SHA256},
        'lanes':lanes,'consumer_lanes':{k:sorted(a['group']+':'+a['name']+':'+a['version'] for a in rows) for k,rows in consumer_resolution.items()},'artifacts':records,'approval':'DECLARED LICENSES VERIFIED; redistribution NOT GRANTED'}

def check_dependencies(work):
    actual=pin_dependencies(work)
    expected=json.loads((ROOT/MANIFEST).read_text())
    native={coord for rows in actual['lanes'].values() for coord in rows}
    pinned=[a for a in expected['artifacts'] if a['group']+':'+a['name']+':'+a['version'] in native]
    if actual['artifacts']!=pinned or actual['lanes']!=expected['lanes'] or expected['gradle']!=actual['gradle']:
        raise ValueError('Frozen dependency graph mismatch')
    return {'status':'PASS','artifacts':len(expected['artifacts']),'lanes':expected['lanes'],
        'consumer_lanes':expected['consumer_lanes'],'sha512':guard.digest((ROOT/MANIFEST).read_bytes())}

def consumer(work, lane, mixed=False, wrong=False,bom=False):
    version = '3.5.16' if lane=='BOOT3' else '4.1.2'
    chosen = 'starter-boot3' if (lane=='BOOT3')!=wrong else 'starter-boot4'
    project = work/('consumer-'+lane+('-mixed' if mixed else '-wrong' if wrong else '-bom' if bom else ''))
    project.mkdir()
    (project/'settings.gradle').write_text("rootProject.name='consumer'\n")
    dependency = "implementation 'dev.udak:"+chosen+":0.1.0-poc'"
    if mixed:
        dependency += "\n implementation 'dev.udak:starter-boot4:0.1.0-poc'" if chosen=='starter-boot3' else "\n implementation 'dev.udak:starter-boot3:0.1.0-poc'"
    (project/'build.gradle').write_text('''plugins { id 'application' }
repositories {
    exclusiveContent {
        forRepository { maven {
            url = uri('''+repr(str(CANDIDATE_BASE/'repository'))+''')
            metadataSources { mavenPom(); ignoreGradleMetadataRedirection() }
        } }
        filter { includeGroup('dev.udak') }
    }
    mavenCentral()
}
dependencies {
    '''+("implementation platform('org.springframework.boot:spring-boot-dependencies:"+version+"')" if mixed or wrong else ("implementation platform('org.springframework.boot:spring-boot-dependencies:"+version+"')" if bom else ''))+'''
    '''+dependency+'''
    implementation('com.h2database:h2:2.3.232') { version { strictly '2.3.232' } }
}
'''+('''configurations.configureEach {
    resolutionStrategy.eachDependency { details ->
        if (details.requested.group == 'org.springframework.boot') details.useVersion('''+repr(version)+''')
        if (details.requested.group == 'org.springframework') details.useVersion('''+repr('6.2.19' if lane=='BOOT3' else '7.0.10')+''')
    }
}
''' if mixed or wrong else '')+'''
java { toolchain { languageVersion = JavaLanguageVersion.of(Runtime.version().feature()) } }
tasks.withType(JavaCompile).configureEach { options.release = 17 }
sourceSets.main.java.srcDirs = ['''+repr(str(ROOT/'starter-testkit/src/main/java'))+''']
application { mainClass = 'dev.udak.startertest.StarterContractMain' }
tasks.named('run') {
    maxHeapSize = '256m'
    jvmArgs '-XX:MaxMetaspaceSize=128m', '-XX:ActiveProcessorCount=2'
    args '''+repr(lane)+(' , '+repr('mixed' if mixed else 'wrong-major') if mixed or wrong else '')+'''
}
tasks.register('consumerResolution') {
    doLast {
        def selected = configurations.runtimeClasspath.resolvedConfiguration.resolvedArtifacts.collect {
            [group:it.moduleVersion.id.group,name:it.name,version:it.moduleVersion.id.version,file:it.file.absolutePath]
        }
        new File('''+repr(str(project/'consumer-resolution.json'))+''').text = groovy.json.JsonOutput.toJson(selected)
    }
}
''')
    return project

def validate_consumer_resolution(project, lane, mixed=False, wrong=False,bom=False):
    artifacts=json.loads((project/'consumer-resolution.json').read_text())
    expected='3.5.16' if lane=='BOOT3' else '4.1.2'
    if {a['version'] for a in artifacts if a['group']=='org.springframework.boot'}!={expected}:raise ValueError('Consumer Boot graph mixed')
    springs={a['version'] for a in artifacts if a['group']=='org.springframework'}
    if springs!={'6.2.19' if lane=='BOOT3' else '7.0.10'}:raise ValueError('Consumer Spring graph mixed')
    chosen='starter-boot3' if (lane=='BOOT3')!=wrong else 'starter-boot4'
    modules=set(MODULES[:4])|({*MODULES[-2:]} if mixed else {chosen})
    actual_modules={a['name'] for a in artifacts if a['group']=='dev.udak'}
    if actual_modules!=modules:raise ValueError('Consumer packaged graph incomplete')
    frozen=json.loads((ROOT/MANIFEST).read_text())
    frozen_hash={a['group']+':'+a['name']+':'+a['version']:a['sha512'] for a in frozen['artifacts']}
    jar_hash={}
    for a in artifacts:
        coord=a['group']+':'+a['name']+':'+a['version']
        jar=Path(a['file'])
        if not jar.is_relative_to(project.parent/'home') and not jar.is_relative_to(CANDIDATE_BASE):raise ValueError('Consumer artifact origin denied')
        if jar.is_symlink() or jar.stat().st_size>24*1024**2:raise ValueError('Consumer artifact denied')
        digest=guard.digest(jar.read_bytes())
        if a['group']=='dev.udak':
            if a['version']!='0.1.0-poc':raise ValueError('Candidate version mismatch')
            own=CANDIDATE_BASE/'repository/dev/udak'/a['name']/'0.1.0-poc'/(a['name']+'-0.1.0-poc.jar')
            if digest!=guard.digest(own.read_bytes()):raise ValueError('Candidate not consumed')
        elif frozen_hash.get(coord)!=digest:raise ValueError('Unfrozen consumer artifact')
        jar_hash[coord]=digest
    expected_external=set(frozen['lanes' if mixed or wrong or bom else 'consumer_lanes']['starter-boot3' if lane=='BOOT3' else 'starter-boot4'])|set(frozen['lanes']['h2'])
    if {a['group']+':'+a['name']+':'+a['version'] for a in artifacts if a['group']!='dev.udak'}!=expected_external:
        raise ValueError('Consumer dependency graph changed')
    return {'status':'PASS','boot_version':expected,'spring_versions':sorted(springs),'pom_only':True,
        'artifacts':sorted(jar_hash),'artifact_sha512':jar_hash}

def candidate_inventory():
    entries=bounded_inventory(CANDIDATE_BASE,500,200*1024**2)
    cli=module('phase6_candidate_paths','udak-cli/udak_cli.py')
    allowed={path.removeprefix('build/phase6/') for path in cli.ARTIFACTS}|{'.owner'}
    for module_name in MODULES:
        for suffix in ('','.md5','.sha1','.sha256','.sha512'):
            allowed.add('repository/dev/udak/'+module_name+'/maven-metadata.xml'+suffix)
        for entry in list(allowed):
            if entry.startswith('repository/dev/udak/'+module_name+'/0.1.0-poc/'):
                for extension in ('.md5','.sha1','.sha256','.sha512'):allowed.add(entry+extension)
    files=[]
    for path,info in entries:
        if stat.S_ISREG(info.st_mode):
            if str(path.relative_to(CANDIDATE_BASE)) not in allowed:raise ValueError('Unknown candidate file preserved')
            files.append(path)
    return sorted(files)

def artifact_hashes():
    candidates=candidate_inventory()
    hashes={'build/phase6/'+str(p.relative_to(CANDIDATE_BASE)):guard.digest(p.read_bytes())
        for p in candidates if p.suffix in ('.jar','.pom','.module')}
    if len(hashes)!=30:raise ValueError('Candidate package inventory incomplete')
    return hashes

def api_compatibility():
    previous=json.loads((ROOT/'evidence/PHASE5-VALIDATION.json').read_text())['source_sha512']
    paths={name for name in sources() if name.split('/')[0] in MODULES[:4] and '/src/main/java/' in name}
    if len(paths)!=22 or not paths<=previous.keys() or hashes(paths)!={name:previous[name] for name in paths}:
        raise ValueError('Existing public sources changed')
    return {'status':'PASS','baseline':'evidence/PHASE5-VALIDATION.json','preserved_sources':len(paths),
        'prior_published_release':'NONE','binary_backward_compatibility':'NOT RUN; no prior published release'}

def candidate_metadata(dependency,api):
    base=CANDIDATE_BASE
    candidates=candidate_inventory()
    entries=[{'path':'build/phase6/'+str(p.relative_to(base)),'size':p.stat().st_size,'sha512':guard.digest(p.read_bytes())}
        for p in candidates if p.suffix in ('.jar','.pom','.module')]
    for m in MODULES[-2:]:
        jar=base/'repository/dev/udak'/m/'0.1.0-poc'/(m+'-0.1.0-poc.jar')
        with zipfile.ZipFile(jar) as archive:
            name='META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports'
            expected='dev.udak.'+('boot3' if m.endswith('3') else 'boot4')+'.UdakAutoConfiguration'
            if archive.read(name).decode().strip()!=expected:raise ValueError('Packaged auto discovery mismatch')
            metadata=json.loads(archive.read('META-INF/spring-configuration-metadata.json'))
            if len(metadata.get('properties',[]))!=10:raise ValueError('Packaged settings metadata missing')
            classes=[i for i in archive.infolist() if i.filename.endswith('.class')]
            if not classes or any(int.from_bytes(archive.read(i)[6:8],'big')!=61 for i in classes):raise ValueError('Java release mismatch')
    sbom={'bomFormat':'CycloneDX','specVersion':'1.5','version':1,'components':[
        {'type':'library','group':a['group'],'name':a['name'],'version':a['version'],
        'purl':'pkg:maven/'+a['group']+'/'+a['name']+'@'+a['version'],
        'hashes':[{'alg':'SHA-512','content':a['sha512']}],
        'licenses':[{'license':{'name':l['name'],'url':l['url']}} for l in a['licenses']]}
        for a in dependency['artifacts']]}
    (base/'SBOM.json').write_text(json.dumps(sbom,indent=2)+'\n')
    notices=['UDAK 0.1.0-poc — PRIVATE EVALUATION CANDIDATE','No UDAK project license or production redistribution permission has been granted.']
    for a in dependency['artifacts']:
        notices.append(a['group']+':'+a['name']+':'+a['version']+' | '+'; '.join(l['name']+' '+l['url'] for l in a['licenses']))
    (base/'NOTICE.txt').write_text('\n'.join(notices)+'\n')
    (base/'API-COMPATIBILITY.json').write_text(json.dumps(api,indent=2)+'\n')
    (base/'CANDIDATE.json').write_text(json.dumps({'version':'0.1.0-poc','status':'PRIVATE CANDIDATE',
        'artifacts':entries,'authorize_publish':False,'release_policy_sha512':guard.digest((ROOT/'tools/phase6-release-policy.json').read_bytes())},indent=2)+'\n')
    candidates=candidate_inventory()
    cli=module('phase6_artifact_paths','udak-cli/udak_cli.py')
    share=[p for p in candidates if 'build/phase6/'+str(p.relative_to(base)) in cli.ARTIFACTS]
    (base/'CHECKSUMS.sha512').write_text('\n'.join(guard.digest(p.read_bytes())+'  '+str(p.relative_to(base)) for p in share)+'\n')
    return [{'path':'build/phase6/'+str(p.relative_to(base)),'size':p.stat().st_size,'sha512':guard.digest(p.read_bytes())}
        for p in candidate_inventory() if 'build/phase6/'+str(p.relative_to(base)) in cli.ARTIFACTS]

SCENARIOS=('DISCOVERY','DISABLED','USER_BEANS','CUSTOM_SINK','JDBC_OPT_IN','NO_DATASOURCE',
    'AMBIGUOUS_DATASOURCES','JDBC_TRANSACTION','VENDOR_REQUIRED','INVALID_LIMITS','UNSAFE_SETTINGS')

def protocol(output,lane,mode=''):
    lines=[line for line in output.splitlines() if line.startswith((lane+' ','ASSERTIONS=','SCENARIO='))]
    expected=('MIXED_STARTERS',) if mode=='mixed' else ('WRONG_BOOT_MAJOR',) if mode=='wrong' else SCENARIOS
    if len(lines)!=2+len(expected) or lines[0]!=lane+' PASS' or not re.fullmatch(r'ASSERTIONS=[1-9][0-9]*',lines[1]) or lines[2:]!=['SCENARIO='+n+':PASS' for n in expected]:
        raise ValueError('Boot protocol incomplete')
    result={'status':'PASS','assertions':int(lines[1].split('=')[1]),'scenarios':list(expected),
        'protocol_sha512':guard.digest(('\n'.join(lines)+'\n').encode())}
    if mode:result['startup_refused']=True
    else:result.update(application_started=True,application_closed=True)
    return result

def main():
    pin = sys.argv[1:]==['--pin-dependencies']
    if sys.argv[1:] and not pin:
        print('PHASE6 INVALID_ARGUMENTS');return 2
    start=time.monotonic()
    result={'schema_version':1,'phase':6,'status':'FAIL','started_at_utc':datetime.now(timezone.utc).isoformat(),
            'steps':[],'boot_lines':{},'negative_consumers':[],'authorize_publish':False,'containers_started':0,'external_publications':0,
            'limits':{'wall_seconds':1800,'gradle_heap_mib':512,'gradle_metaspace_mib':256,'active_cpus':2,'workers':1,
                      'consumer_heap_mib':256,'child_cpu_seconds':120,'workspace_files':20000,'workspace_bytes':2*1024**3,
                      'candidate_files':500,'candidate_bytes':200*1024**2},
            'not_run':['performance/load','cancellation/recovery certification','external publication','production license approval','full legacy demo Gradle build']}
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,guard.interrupted)
    signal.alarm(1800)
    base=None
    created=False
    global CANDIDATE_BASE
    try:
        if shutil.disk_usage(ROOT).free<4*1024**3:raise ValueError('Insufficient disk headroom')
        with workspace() as (work,cleanup):
            CANDIDATE_BASE=work/'candidate'
            base=CANDIDATE_BASE
            base.mkdir();(base/'.owner').write_text(work.name);created=True
            result['cleanup']=cleanup
            os.putenv('TMPDIR',str(work))
            for key in ('_JAVA_OPTIONS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','GRADLE_OPTS','JAVA_OPTS'):os.unsetenv(key)
            result['steps'].append(step('java-version',JAVA+['-version'],work))
            java_version=re.search(r'version \"([0-9]+(?:\.[0-9]+){0,3})(?:[^\"]*)\"',(work/'java-version.output').read_text())
            if not java_version or not 17<=int(java_version[1].split('.')[0])<=24:raise ValueError('Gradle compatible JDK required')
            result['java_runtime_version']=java_version[1]
            result['compile_release']=17
            binary=gradle_distribution(work)
            result['steps'].append(step('resolve',gradle_command(binary,work,ROOT/'starter-testkit','phase6Resolution'),work,timeout=600))
            if pin:
                tasks=[f':{m}:publishAllPublicationsToCandidateRepository' for m in MODULES]
                result['steps'].append(step('package-for-pinning',gradle_command(binary,work,ROOT/'starter-testkit',*tasks),work,timeout=600))
                for lane in ('BOOT3','BOOT4'):
                    project=consumer(work,lane)
                    result['steps'].append(step('pin-consumer-'+lane,gradle_command(binary,work,project,'consumerResolution'),work,timeout=120))
                save(MANIFEST,pin_dependencies(work,pom_consumers=True))
                result['status']='PINNED'
            else:
                result['dependencies']=check_dependencies(work)
                result['source_sha512']=hashes(sources())
                result['harness_sha512']=hashes(HARNESS)
                result['configuration_sha512']=hashes(CONFIG)
                result['manifest_sha512']=hashes((MANIFEST,'tools/phase6-release-policy.json'))
                result['steps'].append(step('prior-g4', ['python3','tools/verify-phase5.py'], work))
                result['documentation']=guard.verify_documents()
                result['steps'].append(step('core-smoke',['./tools/run-core-smoke.sh'],work))
                tasks=[f':{m}:publishAllPublicationsToCandidateRepository' for m in MODULES]
                result['steps'].append(step('package',gradle_command(binary,work,ROOT/'starter-testkit',*tasks),work,timeout=600))
                first=artifact_hashes()
                result['steps'].append(step('repackage',gradle_command(binary,work,ROOT/'starter-testkit',*tasks,'--rerun-tasks'),work,timeout=600))
                if first!=artifact_hashes():raise ValueError('Package reproducibility mismatch')
                result['reproducibility']={'status':'PASS','artifact_sha512':first,'repackaged_artifacts':len(first)}
                result['api_compatibility']=api_compatibility()
                for lane in ('BOOT3','BOOT4'):
                    project=consumer(work,lane)
                    s=step('consumer-'+lane,gradle_command(binary,work,project,'run','consumerResolution'),work,timeout=300)
                    result['steps'].append(s)
                    proof=protocol((work/('consumer-'+lane+'.output')).read_text(),lane)
                    proof['resolution']=validate_consumer_resolution(project,lane)
                    result['boot_lines'][lane.lower()]=proof
                project=consumer(work,'BOOT4',bom=True)
                result['steps'].append(step('consumer-BOOT4-bom',gradle_command(binary,work,project,'run','consumerResolution'),work,timeout=300))
                result['bom_consumer']={'lane':'BOOT4','status':'PASS','protocol':protocol((work/'consumer-BOOT4-bom.output').read_text(),'BOOT4'),
                    'resolution':validate_consumer_resolution(project,'BOOT4',bom=True)}
                for lane,mode in (('BOOT4','mixed'),('BOOT3','wrong'),('BOOT4','wrong')):
                    project=consumer(work,lane,mixed=mode=='mixed',wrong=mode=='wrong')
                    s=step('consumer-'+lane+'-'+mode,gradle_command(binary,work,project,'run','consumerResolution'),work,timeout=300)
                    result['steps'].append(s)
                    result['negative_consumers'].append({'lane':lane,'mode':mode,'status':'PASS',
                        'protocol':protocol((work/('consumer-'+lane+'-'+mode+'.output')).read_text(),lane,mode),
                        'resolution':validate_consumer_resolution(project,lane,mixed=mode=='mixed',wrong=mode=='wrong')})
                result['steps'].append(step('cli-contract',['python3','tools/test-phase6-cli.py'],work,timeout=60))
                result['artifacts']=candidate_metadata(json.loads((ROOT/MANIFEST).read_text()),result['api_compatibility'])
                for field,names in (('source_sha512',sources()),('harness_sha512',HARNESS),('configuration_sha512',CONFIG),('manifest_sha512',(MANIFEST,'tools/phase6-release-policy.json'))):
                    if result[field]!=hashes(names):raise ValueError('Execution input changed')
                result['status']='PASS'
    except BaseException as error:
        result['status']='FAIL'
        result['failure_type']=type(error).__name__
        import ast
        tree=ast.parse(Path(__file__).read_text())
        fixed_messages={node.exc.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Raise) and isinstance(node.exc,ast.Call)
            and isinstance(node.exc.func,ast.Name) and node.exc.func.id=='ValueError' and node.exc.args and isinstance(node.exc.args[0],ast.Constant)}
        if type(error) is ValueError and str(error) in fixed_messages:result['failure_reason']=str(error)
        if isinstance(error,RuntimeError):
            try:result['failed_step']=json.loads(str(error))
            except ValueError:pass
        if isinstance(error,KeyboardInterrupt):result['failure_type']='Interrupted'
    finally:
        if created:
            result['candidate_cleanup']={'status':'PASS' if result.get('cleanup',{}).get('status')=='PASS' else 'PRESERVED_UNKNOWN',
                'temporary_files_removed':result.get('cleanup',{}).get('candidate_files_removed',0),'temporary_bytes_removed':result.get('cleanup',{}).get('candidate_bytes_removed',0),
                'temporary_directory_remaining':base.exists()}
        signal.alarm(0)
        result['elapsed_seconds']=round(time.monotonic()-start,3)
        if not pin:save(REPORT,result)
        else:save('.git/udak-phase6/PINNING-RESULT.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_sha512','harness_sha512','configuration_sha512','manifest_sha512','artifacts')},ensure_ascii=False))
    return 0 if result['status'] in ('PASS','PINNED') else 1

if __name__=='__main__':raise SystemExit(main())
