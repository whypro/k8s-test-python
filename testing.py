from kubernetes import client, config, watch
import os
import yaml
import requests
import time

# Configs can be set in Configuration class directly or using helper utility
config.load_kube_config('/Users/haoyuwang/Others/evm-test-kubeconfig')
#config.load_kube_config()
test_namespace = 'default'
sleep_time_s = 0.05


def test_apiserver(timeout):
    result = dict(success=0, error=0)
    api = client.CoreV1Api()
    start = time.time()
    while time.time() < start + timeout:
        # sleep 50ms
        time.sleep(0.05)
        try:
            pods = api.list_namespaced_pod('kube-system')
        except Exception as e:
            # print e
            result['error'] += 1
            continue
        result['success'] += 1

    return result


def test_service(timeout):
    result = dict(success=0, error=0)
    api = client.CoreV1Api()
    services = api.list_namespaced_service(test_namespace)

    start = time.time()
    while time.time() < start + timeout:
        # sleep 50ms
        time.sleep(0.05)
        for service in services.items:
            ip = service.spec.cluster_ip
            if not ip:
                continue
            port = service.spec.ports[0].port
            url = ip+':'+str(port)
            try:
                rsp = requests.get(url, timeout=5)
            except Exception as e:
                # print e
                result['error'] += 1
                continue

            if rsp.status_code != 200:
                result['error'] += 1
                continue

            result['success'] += 1

    return result


def test_create_service(filename):
    with open(filename, 'r') as f:
        obj = yaml.load(f)
        namespace = obj['metadata']['namespace']

    v1_api = client.CoreV1Api()
    try:
        service = v1_api.create_namespaced_service(namespace, obj)
    except Exception as e:
        print e
        return False

    return True


def test_delete_service(filename):
    with open(filename, 'r') as f:
        obj = yaml.load(f)
        name = obj['metadata']['name']
        namespace = obj['metadata']['namespace']

    v1_api = client.CoreV1Api()
    try:
        service = v1_api.delete_namespaced_service(name, namespace)
    except Exception as e:
        print e
        return False

    return True


def test_create_deployment(filename, timeout):
    with open(filename, 'r') as f:
        obj = yaml.load(f)
        # name = obj['metadata']['name']
        namespace = obj['metadata']['namespace']
        labels = obj['spec']['template']['metadata']['labels']
        replicas = obj['spec']['replicas']

    label_selector = ','.join(['{0}={1}'.format(k, v) for k, v in labels.items()])

    v1beta1_api = client.ExtensionsV1beta1Api()
    try:
        deployment = v1beta1_api.create_namespaced_deployment(namespace, obj)
    except Exception as e:
        print e
        return False

    start = time.time()
    success = False
    while time.time() < start + timeout and not success:
        time.sleep(sleep_time_s)
        deployments = v1beta1_api.list_namespaced_deployment(namespace)
        for d in deployments.items:
            if d.metadata.uid == deployment.metadata.uid:
                success = True
                break   # break for
    if not success:
        return False
    end = time.time()
    print 'create deployment success in {0}s'.format(end-start)

    v1_api = client.CoreV1Api()
    start = time.time()
    desired = False
    while time.time() < start + timeout and not desired:
        time.sleep(sleep_time_s)
        all_running = True
        pods = v1_api.list_namespaced_pod(namespace, label_selector=label_selector)
        for p in pods.items:
            if p.status.phase != 'Running':
                all_running = False
                break
        if len(pods.items) == replicas and all_running:
            desired = True
    if not desired:
        return False
    end = time.time()
    print 'all pods started in {0}s'.format(end-start)

    return True


def test_delete_deployment(filename, timeout):
    with open(filename, 'r') as f:
        obj = yaml.load(f)
        name = obj['metadata']['name']
        namespace = obj['metadata']['namespace']
        labels = obj['spec']['template']['metadata']['labels']
        replicas = obj['spec']['replicas']

    label_selector = ','.join(['{0}={1}'.format(k, v) for k, v in labels.items()])

    v1beta1_api = client.ExtensionsV1beta1Api()
    delete_options = client.V1DeleteOptions(propagation_policy='Foreground', grace_period_seconds=5)
    try:
        deployment = v1beta1_api.delete_namespaced_deployment(name, namespace, delete_options)
    except Exception as e:
        print e
        return False

    start = time.time()
    desired = False
    while time.time() < start + timeout and not desired:
        time.sleep(sleep_time_s)
        deleted = True
        deployments = v1beta1_api.list_namespaced_deployment(namespace)
        for d in deployments.items:
            if d.metadata.name == name:
                deleted = False
                break   # break for
        if deleted:
            desired = True
    if not desired:
        return False
    end = time.time()
    print 'delete deployment success in {0}s'.format(end-start)

    v1_api = client.CoreV1Api()
    start = time.time()
    desired = False
    while time.time() < start + timeout and not desired:
        time.sleep(sleep_time_s)
        pods = v1_api.list_namespaced_pod(namespace, label_selector=label_selector)
        if not pods.items:
            desired = True
    if not desired:
        return False
    end = time.time()
    print 'all pods deleted in {0}s'.format(end-start)

    return True


def test_watch_pod_events(timeout):
    v1_api = client.CoreV1Api()

    start = time.time()
    w = watch.Watch()
    for event in w.stream(v1_api.list_pod_for_all_namespaces):
        print("Event: %s %s %s" % (event['type'], event['object'].kind, event['object'].metadata.name))
        if time.time() > start + timeout:
            break


def _check_pod_status_consistent(pods_a, pods_b):

    pods_a_set = set([p.metadata.uid for p in pods_a])
    pods_a_map = {p.metadata.uid: p for p in pods_a}
    pods_b_set = set([p.metadata.uid for p in pods_b])
    pods_b_map = {p.metadata.uid: p for p in pods_b}

    deleted_pods_set = pods_a_set - pods_b_set
    created_pods_set = pods_b_set - pods_a_set
    common_pods_set = pods_a_set & pods_b_set
    status_changed_pods_set = set()

    for pod_uid in common_pods_set:
        if pods_a_map[pod_uid].status.phase != pods_b_map[pod_uid].status.phase:
            print 'pod status phase from %s to %s' % (pods_a_map[pod_uid].status.phase, pods_b_map[pod_uid].status.phase)
            status_changed_pods_set.add(pod_uid)
        if not pods_a_map[pod_uid].status.container_statuses or not pods_a_map[pod_uid].status.container_statuses:
            continue

        container_statuses = map(lambda x, y: (x, y), list(pods_a_map[pod_uid].status.container_statuses), list(pods_b_map[pod_uid].status.container_statuses))
        for cs in container_statuses:
            if cs[0].state != cs[1].state:
                print 'pod container state change'
                status_changed_pods_set.add(pod_uid)
            if cs[0].restart_count != cs[1].restart_count:
                print 'pod restart, from %s to %s' % (cs[0].restart_count, cs[1].restart_count)
                status_changed_pods_set.add(pod_uid)

    deleted_pods = {pod_uid: pods_a_map[pod_uid] for pod_uid in deleted_pods_set}
    created_pods = {pod_uid: pods_b_map[pod_uid] for pod_uid in created_pods_set}
    status_changed_pods = {pod_uid: pods_a_map[pod_uid] for pod_uid in status_changed_pods_set}
    return deleted_pods, created_pods, status_changed_pods


def test_pod_status_consistent(timeout):
    last_pods = None
    current_pods = None
    v1_api = client.CoreV1Api()
    start = time.time()
    while time.time() < start + timeout:
        time.sleep(sleep_time_s)
        pods = v1_api.list_pod_for_all_namespaces()
        if last_pods is None:
            last_pods = pods.items
        current_pods = pods.items
        deleted_pods, created_pods, status_changed_pods = _check_pod_status_consistent(last_pods, current_pods)
        if deleted_pods or created_pods or status_changed_pods:
            print '======'
            print 'deleted:', [v.metadata.name for k, v in deleted_pods.items()]
            print 'created:', [v.metadata.name for k, v in created_pods.items()]
            print 'status_changed:', [v.metadata.name for k, v in status_changed_pods.items()]
            print '======'
        last_pods = current_pods


if __name__ == "__main__":
    #print test_apiserver(60)
    #print test_service(60)

    print test_create_deployment('nginx-deploy.yaml', 300)
    #print test_delete_deployment('nginx-deploy.yaml', 300)
    #test_watch_pod_events(300)
    #test_pod_status_consistent(300)
    print test_create_service('nginx-svc.yaml')
    #print test_delete_service('nginx-svc.yaml')
