/** Contract tests for the realtime service and board, using a controlled bus/RPC. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

class EventBus extends EventTarget {
    trigger(type, detail) { this.dispatchEvent(new CustomEvent(type, { detail })); }
}
const defer = () => {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return { promise, resolve };
};
const tick = () => new Promise((done) => setImmediate(done));

async function loadFrontend() {
    const services = new Map();
    const components = new Map();
    const mounted = [];
    const starting = [];
    const unmounting = [];
    const context = vm.createContext({ console, Intl, Date, Set, Map, Promise });
    const registry = { category: (category) => ({
        add: (name, value) => (category === 'services' ? services : components).set(name, value),
    }) };
    const owl = {
        Component: class {}, EventBus, xml: () => '', useState: (state) => state,
        onWillStart: (fn) => starting.push(fn), onMounted: (fn) => mounted.push(fn),
        onWillUnmount: (fn) => unmounting.push(fn),
    };
    const user = { hasGroup: async () => true, context: { allowed_company_ids: [42] } };
    let componentServices;
    const modules = {
        '@odoo/owl': owl,
        '@web/core/registry': { registry },
        '@web/core/user': { user },
        '@web/core/utils/hooks': {
            useService: (name) => componentServices[name],
            useBus: (bus, name, fn) => mounted.push(() => bus.addEventListener(name, fn)),
        },
    };
    const cache = new Map();
    async function linker(name) {
        if (!cache.has(name)) {
            const values = modules[name];
            assert.ok(values, `Unexpected Odoo dependency ${name}`);
            const module = new vm.SyntheticModule(Object.keys(values), function () {
                for (const [key, value] of Object.entries(values)) this.setExport(key, value);
            }, { context });
            cache.set(name, module);
        }
        return cache.get(name);
    }
    const namespaces = [];
    for (const name of ['staff_alert_systray.js', 'table_board.js']) {
        const source = await readFile(new URL(`../addons/qclub_billiard/static/src/js/${name}`, import.meta.url), 'utf8');
        const module = new vm.SourceTextModule(source, { context });
        await module.link(linker);
        await module.evaluate();
        namespaces.push(module.namespace);
    }
    return { services, namespaces, mounted, starting, unmounting, user,
        setServices(value) { componentServices = value; } };
}

test('test_rt_006_live_toasts_drop_offline_replay_and_reconnect_backlog', async () => {
    const frontend = await loadFrontend();
    const bus = new EventBus();
    const callbacks = new Map();
    const channels = [];
    Object.assign(bus, {
        workerState: 'CONNECTED', subscribe: (kind, fn) => callbacks.set(kind, fn),
        addChannel: (channel) => channels.push(channel),
    });
    let last = 100;
    const orm = { call: async (model, method, args, kwargs) => {
        assert.equal(model, 'qclub.table');
        assert.equal(method, 'get_staff_realtime_subscription');
        assert.equal(kwargs.context.allowed_company_ids[0], 42);
        return { channels: ['qclub.staff:7'], last_notification_id: last };
    } };
    const service = frontend.services.get('qclub_realtime').start({}, { bus_service: bus, orm });
    assert.equal(await service.ready, true);
    assert.deepEqual(channels, ['qclub.staff:7']);
    const received = [];
    service.addEventListener('qclub.alert', ({ detail }) => received.push(detail));
    const emit = (id) => callbacks.get('qclub.alert')({ booking_id: id }, { id });
    emit(99);
    emit(100);
    emit(101);
    assert.equal(received.length, 1);
    bus.trigger('BUS:DISCONNECT');
    emit(102);
    last = 104;
    bus.trigger('BUS:RECONNECT');
    emit(103);
    await tick();
    emit(104);
    emit(105);
    assert.deepEqual(received.map((item) => item.booking_id), [101, 105]);
    let board;
    service.addEventListener('qclub.board_update', ({ detail }) => { board = detail.table_id; });
    callbacks.get('qclub.board_update')({ table_id: 9 });
    assert.equal(board, 9);
});

test('test_rt_007_non_staff_never_requests_or_subscribes_channels', async () => {
    const frontend = await loadFrontend();
    frontend.user.hasGroup = async () => false;
    const fail = () => assert.fail('Non-staff accessed realtime data');
    const service = frontend.services.get('qclub_realtime').start({}, {
        bus_service: { subscribe: fail, addChannel: fail }, orm: { call: fail },
    });
    assert.equal(await service.ready, false);
});

test('test_rt_002_incremental_refresh_handles_event_during_initial_read', async () => {
    const frontend = await loadFrontend();
    const initial = defer();
    const incremental = defer();
    const calls = [];
    const realtime = Object.assign(new EventBus(), { ready: Promise.resolve(true), context: () => ({}) });
    const orm = { call: (model, method, args) => {
        calls.push(args);
        return calls.length === 1 ? initial.promise : incremental.promise;
    } };
    frontend.setServices({ orm, qclub_realtime: realtime });
    const board = new frontend.namespaces[1].TableBoard();
    board.setup();
    await Promise.all(frontend.starting.map((fn) => fn()));
    // Owl's useBus installs its listener before the board begins its initial read.
    const mounted = frontend.mounted.map((fn) => fn());
    realtime.trigger('qclub.board_update', { table_id: 2 });
    initial.resolve([{ id: 1, name: 'A', booking: false }, { id: 2, name: 'B', booking: false }]);
    await Promise.all(mounted);
    await tick();
    assert.equal(JSON.stringify(calls), '[[],[[2]]]');
    incremental.resolve([{ id: 2, name: 'B', booking: { name: 'QB-2' } }]);
    await board.updates;
    assert.equal(board.state.tables[0].id, 1);
    assert.equal(board.state.tables[1].booking.name, 'QB-2');
    assert.equal(board.state.loading, false);
    frontend.unmounting.forEach((fn) => fn());
    realtime.trigger('qclub.board_update', { table_id: 1 });
    await board.updates;
    assert.equal(calls.length, 2);
});

test('test_rt_004_systray_toast_uses_allowlisted_fields_as_plain_text', async () => {
    const frontend = await loadFrontend();
    const realtime = Object.assign(new EventBus(), { ready: Promise.resolve(true) });
    const toasts = [];
    frontend.setServices({ qclub_realtime: realtime, notification: { add: (...args) => toasts.push(args) } });
    const systray = new frontend.namespaces[0].StaffAlertSystray();
    systray.setup();
    await Promise.all(frontend.starting.map((fn) => fn()));
    frontend.mounted.forEach((fn) => fn());
    for (const kind of ['booking_submitted', 'deposit_confirmed', 'cancelled', 'player_joined']) {
        realtime.trigger('qclub.alert', {
            kind, booking_name: '<img src=x onerror=alert(1)>', table_name: 'Snooker A',
            start: '2026-11-06T03:30:00', end: '2026-11-06T04:30:00',
            amount: 12345, email: 'private@example.invalid',
        });
    }
    assert.equal(toasts.length, 4);
    assert.ok(toasts[0][0].startsWith('New booking <img'));
    for (const [message, options] of toasts) {
        assert.equal(typeof message, 'string');
        assert.ok(message.includes('Snooker A'));
        assert.ok(message.includes('2:00 pm'));
        assert.ok(!message.includes('12345'));
        assert.ok(!message.includes('private@example.invalid'));
        assert.equal(options.sticky, false);
    }
});

test('test_rt_002_rt_003_board_update_replaces_upcoming_for_one_table', async () => {
    const frontend = await loadFrontend();
    const realtime = Object.assign(new EventBus(), { ready: Promise.resolve(true), context: () => ({}) });
    const upcoming = [{ start: '2026-11-06T03:30:00Z', end: '2026-11-06T04:30:00Z' }];
    const table = { id: 2, name: 'B', booking: false, upcoming: [] };
    const other = { id: 1, name: 'A', booking: false, upcoming: [] };
    let rows = [other, table];
    const calls = [];
    const orm = { call: async (_model, _method, args) => {
        calls.push(args);
        return rows;
    } };
    frontend.setServices({ orm, qclub_realtime: realtime });
    const board = new frontend.namespaces[1].TableBoard();
    board.setup();
    await Promise.all(frontend.starting.map((fn) => fn()));
    await Promise.all(frontend.mounted.map((fn) => fn()));

    for (const [state, slots] of [['confirmed', upcoming], ['cancelled', []]]) {
        rows = [{ ...table, upcoming: slots }];
        realtime.trigger('qclub.board_update', { table_id: table.id, booking_id: 9, state });
        await board.updates;
        assert.equal(board.state.tables[0], other);
        assert.equal(board.state.tables[1].upcoming, slots);
    }
    assert.equal(JSON.stringify(calls), '[[],[[2]],[[2]]]');
    assert.match(board.timeLabel(upcoming[0].start), /^2:00\s+pm$/);
});
