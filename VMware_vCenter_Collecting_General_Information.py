# coding=utf-8
import rest_requests as requests
import rest_json as json

# form HP/uCMDB
import _vmware_vim_base
import logger
import modeling

from com.hp.ucmdb.discovery.library.credentials.dictionary import ProtocolDictionaryManager

from appilog.common.system.types.vectors import ObjectStateHolderVector
from appilog.common.system.types import ObjectStateHolder


# Для игнорирования ошибки о просроченном сертификате
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning) # Suppress only the single warning from urllib3 needed.

# Фукнция определения типа OS на основе полного названия OS
def definition(OS):
    if OS:
        unixKeyWord = ['redhat', 'red hat', 'rhel', 'ubuntu', 'centos', 'suse', 'opensuse', 'open suse', 'coreos',
                       'debian', 'openbsd', 'freebsd', 'linux']
        winKeyWord = ['win', 'windows']
        esxKeyword = ['esx', 'esxi']
        unixMatcher = [word for word in unixKeyWord if word in OS.lower()]
        winMatcher = [word for word in winKeyWord if word in OS.lower()]
        esxMatcher = [word for word in esxKeyword if word in OS.lower()]
        if unixMatcher:
            return 'unix'
        elif winMatcher:
            return 'nt'
        elif esxMatcher:
            return 'vmware_esx_server'
        else:
            logger.debug("unrecognized guest summary:%s" % OS)
            return 'host_node'
    return 'host_node'

def ConnectionVcenter(host_ip, userName, passwd):
    # Создание сессии и получение токена
    sess = requests.post("https://" + host_ip + "/rest/com/vmware/cis/session", auth=(userName, passwd), verify=False)
    session_id = sess.json()['value']

    # Парсинг данных общих данных
    jsonData = requests.get("https://" + host_ip + "/rest/vcenter/vm", verify=False, headers={"vmware-api-session-id": session_id})
    jsonData = json.loads(jsonData.text)  # Переводим json в словарь

    # Форматирование uuid для создания serial_number в формате: VMWARE-42 39 98 C5 1B 73 57 1B-68 AF BD FB A0 AF DA ED
    def formated_uuid(uuid):
        no_hyphen_list = list(uuid.replace('-', ''))
        for i in range(int(len(no_hyphen_list) / 2)):
            no_hyphen_list.insert(i * 3 + 2, ' ')
        hyphen_pos = int(len(no_hyphen_list) / 2 - 1)
        no_hyphen_list[hyphen_pos] = '-'
        serial_number = 'VMware-' + ''.join(no_hyphen_list).rstrip()
        return serial_number

    for i in range(len(jsonData['value'])):
        vm = jsonData['value'][i]['vm']  # Для формирования запроса получения uuid
        # Получаем UUID
        getUuid = requests.get("https://vc.itpqm.lcl/rest/vcenter/vm/" + vm, verify=False, headers={"vmware-api-session-id": session_id})
        getUuid = json.loads(getUuid.text)                          # Переводим json в словарь

        uuid = getUuid['value']['identity']['bios_uuid']            # Вычленяем uuid
        guest_OS = getUuid['value']['guest_OS']                     # Вычленяем OS
        type_OS = definition(guest_OS)                              # Определяем тип OS
        mac = getUuid['value']['nics'][0]['value']['mac_address']   # Вычленяем мак
        serial_number = formated_uuid(uuid)

        # Добавляем в первоначальный словарь
        jsonData['value'][i]['uuid'] = uuid
        jsonData['value'][i]['serial_number'] = serial_number
        jsonData['value'][i]['guest_OS'] = guest_OS
        jsonData['value'][i]['type_OS'] = type_OS
        jsonData['value'][i]['mac'] = mac

    return jsonData

def DiscoveryMain(Framework):
    OSHVResult = ObjectStateHolderVector()

    # Получение входных данных
    ip = Framework.getDestinationAttribute("ip_address")
    host_id = Framework.getTriggerCIData('host_id')

    protocols = Framework.getAvailableProtocols(ip, _vmware_vim_base.VimProtocol.SHORT)
    user = None
    passwd = None

    for cred in protocols:
        protocol = ProtocolDictionaryManager.getProtocolById(cred)
        user = protocol.getProtocolAttribute('protocol_username')
        passwd = protocol.getProtocolAttribute('protocol_password')

    machineData = ConnectionVcenter(ip, user, passwd)
    nodeHostOsh = modeling.createOshByCmdbId('node', host_id)

    for i in range(len(machineData['value'])):
        # Создание хоста, КЕ - WIN, UNIX и тд
        hostOsh = ObjectStateHolder(machineData['value'][i]['type_OS'])
        try:
            hostOsh.setStringAttribute('host_key', machineData['value'][i]['mac'])
        except:
            hostOsh.setStringAttribute('host_key', machineData['value'][i]['uuid'])

        hostOsh.setBoolAttribute('host_iscomplete', 1)
        if machineData['value'][i]['type_OS'] == 'nt':
            hostOsh.setStringAttribute('os_family', 'windows')
        elif machineData['value'][i]['type_OS'] == 'unix':
            hostOsh.setStringAttribute('os_family', 'unix')

        hostOsh.setStringAttribute('serial_number', machineData['value'][i]['serial_number'])
        hostOsh.setStringAttribute('name', machineData['value'][i]['name'].lower())
        hostOsh.setStringAttribute('data_description', machineData['value'][i]['guest_OS'])

        # Создание КЕ - vmware_host_resource
        dataNode = ObjectStateHolder('vmware_host_resource')
        dataNode.setAttribute('data_name', machineData['value'][i]['name'])
        dataNode.setStringAttribute('vm_id', machineData['value'][i]['vm'])
        dataNode.setIntegerAttribute('vm_memory_size', machineData['value'][i]['memory_size_MiB'])
        dataNode.setStringAttribute('power_state', machineData['value'][i]['power_state'])
        dataNode.setIntegerAttribute('vm_num_cpus', machineData['value'][i]['cpu_count'])
        dataNode.setStringAttribute('vm_uuid', machineData['value'][i]['uuid'])
        dataNode.setStringAttribute('serial_number', machineData['value'][i]['serial_number'])

        dataNode.setContainer(hostOsh)
        dataNode.setContainer(nodeHostOsh)
        hostOsh.setContainer(nodeHostOsh)

        OSHVResult.add(dataNode)
    return OSHVResult
